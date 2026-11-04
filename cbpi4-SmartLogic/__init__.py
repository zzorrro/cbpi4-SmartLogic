import asyncio
import logging
from cbpi.api import *
import time

logger = logging.getLogger(__name__)

@parameters([
    Property.Number(label="P", configurable=True, default_value=117.0795, description="P Value of PID"),
    Property.Number(label="I", configurable=True, default_value=0.2747, description="I Value of PID"),
    Property.Number(label="D", configurable=True, default_value=41.58, description="D Value of PID"),
    Property.Select(label="SampleTime", options=[2,5], description="PID Sample time in seconds. Default: 5"),
    Property.Number(label="Max_Output", configurable=True, default_value=100, description="Direct heating power outside mash range (%)"),
    Property.Number(label="Mash_Max_Power", configurable=True, default_value=50, description="Max PID power during mash (%)"),
    Property.Number(label="Boil_Power", configurable=True, default_value=60, description="Power for steady boil after transition (%)"),
    Property.Number(label="Mash_Min_Temp", configurable=True, default_value=40, description="Start of mash range (°C)"),
    Property.Number(label="Mash_Max_Temp", configurable=True, default_value=85, description="End of mash range (°C)"),
    Property.Number(label="Boil_Transition_Temp", configurable=True, default_value=98, description="Temp to switch to boil power (°C)")
])
class SmartLogic(CBPiKettleLogic):

    async def on_stop(self):
        await self.actor_off(self.heater)

    async def run(self):
        try:
            self.TEMP_UNIT = self.get_config_value("TEMP_UNIT", "C")
            sampleTime = int(self.props.get("SampleTime", 5))
            
            p = float(self.props.get("P", 117.0795))
            i = float(self.props.get("I", 0.2747))
            d = float(self.props.get("D", 41.58))
            
            max_out = int(self.props.get("Max_Output", 100))
            mash_max_power = int(self.props.get("Mash_Max_Power", 50))
            boil_power = int(self.props.get("Boil_Power", 60))
            
            mash_min = float(self.props.get("Mash_Min_Temp", 40))
            mash_max = float(self.props.get("Mash_Max_Temp", 85))
            boil_transition = float(self.props.get("Boil_Transition_Temp", 98))
            
            if self.TEMP_UNIT == "F":
                mash_min = (mash_min * 9/5) + 32
                mash_max = (mash_max * 9/5) + 32
                boil_transition = (boil_transition * 9/5) + 32

            self.kettle = self.get_kettle(self.id)
            self.heater = self.kettle.heater
            self.heater_actor = self.cbpi.actor.find_by_id(self.heater)
            
            heat_percent_old = -1
            pid_active = False
            pid = None

            self.manual_override_active = False
            self.current_phase = None

            await self.actor_on(self.heater, max_out)

            while self.running == True:
                sensor_data = self.get_sensor_value(self.kettle.sensor)
                if sensor_data is None:
                    await asyncio.sleep(sampleTime)
                    continue
                    
                current_temp = float(sensor_data.get("value", 0))
                target_temp = self.get_kettle_target_temp(self.id)
                
                try:
                    current_kettle_power = float(self.heater_actor.power)
                except:
                    current_kettle_power = 0
                
                if current_temp >= boil_transition:
                    new_phase = "BOIL"
                elif mash_min <= current_temp <= mash_max:
                    new_phase = "MASH"
                else:
                    new_phase = "HEAT"

                if new_phase == "BOIL":
                    if pid_active:
                        pid_active = False
                        logger.info(f"SmartLogic: Boiling reached ({current_temp}°C).")
                    desired_auto_power = boil_power
                    
                elif new_phase == "MASH":
                    if not pid_active:
                        pid = PIDArduino(sampleTime, p, i, d, 0, mash_max_power)
                        pid_active = True
                        logger.info(f"SmartLogic: Entered mash range. PID ON.")
                    pid._outputMax = mash_max_power
                    desired_auto_power = pid.calc(current_temp, target_temp)
                    
                else:
                    if pid_active:
                        pid_active = False
                        logger.info(f"SmartLogic: Left mash range.")
                    desired_auto_power = max_out

                if self.current_phase != new_phase:
                    self.manual_override_active = False
                    self.current_phase = new_phase
                    heat_percent = desired_auto_power
                    logger.info(f"PHASE CHANGE to {new_phase}! Manual override reset. Power: {desired_auto_power}%")
                
                else:
                    if new_phase == "MASH":
                        if self.manual_override_active:
                            self.manual_override_active = False
                            logger.info("SmartLogic: Mash phase. Manual override BLOCKED.")
                        heat_percent = desired_auto_power
                        
                    else:
                        if self.manual_override_active:
                            heat_percent = current_kettle_power
                        else:
                            if abs(current_kettle_power - desired_auto_power) > 0.5:
                                self.manual_override_active = True
                                heat_percent = current_kettle_power # ИСПРАВЛЕНИЕ: сразу берем ручное значение
                                logger.info(f"SmartLogic: Manual override activated at {current_kettle_power}%")
                            else:
                                heat_percent = desired_auto_power

                if heat_percent != heat_percent_old or heat_percent != current_kettle_power:
                    await self.actor_set_power(self.heater, heat_percent)
                    heat_percent_old = heat_percent
                
                await asyncio.sleep(sampleTime)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("SmartLogic Error {}".format(e))
        finally:
            self.running = False
            await self.actor_off(self.heater)


class PIDArduino(object):
    def __init__(self, sampleTimeSec, kp, ki, kd, outputMin=float('-inf'),
                 outputMax=float('inf'), getTimeMs=None):
        if kp is None: raise ValueError('kp must be specified')
        if ki is None: raise ValueError('ki must be specified')
        if kd is None: raise ValueError('kd must be specified')
        if float(sampleTimeSec) <= float(0): raise ValueError('sampleTimeSec must be greater than 0')
        if outputMin >= outputMax: raise ValueError('outputMin must be less than outputMax')

        self._logger = logging.getLogger(type(self).__name__)
        self._Kp = kp
        self._Ki = ki * sampleTimeSec
        self._Kd = kd / sampleTimeSec
        self._sampleTime = sampleTimeSec * 1000
        self._outputMin = outputMin
        self._outputMax = outputMax
        self._iTerm = 0
        self._lastInput = 0
        self._lastOutput = 0
        self._lastCalc = 0

        if getTimeMs is None:
            self._getTimeMs = self._currentTimeMs
        else:
            self._getTimeMs = getTimeMs

    def calc(self, inputValue, setpoint):
        now = self._getTimeMs()
        if (now - self._lastCalc) < self._sampleTime:
            return self._lastOutput

        error = setpoint - inputValue
        dInput = inputValue - self._lastInput

        if self._lastOutput < self._outputMax and self._lastOutput > self._outputMin:
            self._iTerm += self._Ki * error
            self._iTerm = min(self._iTerm, self._outputMax)
            self._iTerm = max(self._iTerm, self._outputMin)

        p = self._Kp * error
        i = self._iTerm
        d = -(self._Kd * dInput)

        self._lastOutput = p + i + d
        self._lastOutput = min(self._lastOutput, self._outputMax)
        self._lastOutput = max(self._lastOutput, self._outputMin)

        self._lastInput = inputValue
        self._lastCalc = now
        return self._lastOutput

    def _currentTimeMs(self):
        return time.time() * 1000

def setup(cbpi):
    cbpi.plugin.register("SmartLogic", SmartLogic)
