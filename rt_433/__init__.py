'''Race transponder (433MHz)'''

import json
import logging
import serial
import serial.tools.list_ports
import threading
import time

from enum import Enum
from struct import pack
from RHRace import WinCondition
import Results
from VRxControl import VRxController

RETRY_COUNT = 2

logger = logging.getLogger(__name__)

class RaceInfo():
    def __init__(self, pos, lap, secs, hunds, started, idx):
        self.pos = pos
        self.lap = lap
        self.secs = secs
        self.hunds = hunds
        self.started = started
        self.chn_idx = idx

    def toInt(self):
        value = 0
        value |= self.pos << 0
        value |= self.lap << 3
        value |= self.secs << 7
        value |= self.hunds << 13
        value |= self.started << 20
        value |= self.chn_idx << 21
        return value

    def __str__(self):
        return "RaceInfo: pos={}, lap={}, time={}.{}, started={}, channel={}".format(self.pos, self.lap, self.secs, self.hunds, self.started, self.chn_idx)

class RaceMessage():
    def __init__(self, message, channel, seq_id):
        self.message = message
        self.chn_idx = channel
        self.seq_id = seq_id

    def toBytes(self):
        message = self.message
        if len(message) < 6:
            message.ljust(6)
        elif len(message) > 6:
            message = message[:6]
        flags = 0
        flags |= self.seq_id & int('0b111', 2)
        flags |= self.chn_idx << 3
        result = pack('< B 6s B', flags, bytes(message, 'utf-8'), 0x00)
        return result

    def __str__(self):
        return "RaceMessage: message={}, channel={}, seq_id={}".format(self.message, self.chn_idx, self.seq_id)

class CH_IDX(Enum):
    R1 = 0
    R2 = 1
    R3 = 2
    R4 = 3
    R5 = 4
    R6 = 5
    R7 = 6
    R8 = 7
    F2 = 8
    F4 = 9
    BROADCAST = 0xF

def registerHandlers(args):
    if 'registerFn' in args:
        args['registerFn'](RaceTransponderController433(
            'rt433',
            'RaceTransponder433'
        ))

def initialize(**kwargs):
    if 'Events' in kwargs:
        kwargs['Events'].on('VRxC_Initialize', 'VRx_register_rt433', registerHandlers, {}, 75)

class RaceTransponderController433(VRxController):
    def __init__(self, name, label):
        super().__init__(name, label)

        self.pilotChannels = []

        self.raceInfoMap = {}
        self.raceMsgQueue = []
        self.raceInfoQueue = []

        self.currentSequenceId = 0

        self.lock = threading.Lock()

    def __discoverPort(self):
        port = self.racecontext.rhdata.get_option('rt433_port', None)
        if port:
            self.serial_port_name = port
            logger.info("RaceTransponder433: Using port {} from config for Laptimer Comm module".format(port))
            self.ready = True
            return
        else:
            logger.warning("RaceTransponder433: No comm port configured, discovering...")
            ports = serial.tools.list_ports.comports()
            if len(ports):
                port_name = ""
                for port in ports:
                    if "USB" in port.device:
                        port_name = port.device
                        break
                if port_name:
                    logger.warning("RaceTransponder433: Got: " + port_name)
                    self.racecontext.rhdata.set_option('rt433_port', port_name)
                    self.serial_port_name = port_name
                    self.ready = True
                    return

            logger.warning("RaceTransponder433: No usable comm port found")
            self.ready = False

    def __startCommLoop(self):
        commThread = threading.Thread(target=self.__commLoopFunction, args=(self.serial_port_name,))
        commThread.start()

    def __commLoopFunction(self, serial_name):
        s = serial.Serial()
        s.baudrate = 9600
        s.port = serial_name
        s.open()
        s.reset_input_buffer()
        s.reset_output_buffer()
        if s.isOpen() == True:
            while True:
                if len(self.raceInfoQueue):
                    self.__sendRaceInfo(s)
                if len(self.raceMsgQueue):
                    self.__sendRaceMsg(s)
                time.sleep(0.05)

    def __incSeqId(self):
        self.currentSequenceId = (self.currentSequenceId + 1) & int('0b111', 2)

    def __printPayload(self, payload):
        logger.debug("payload: " + ' '.join('{:02x}'.format(x) for x in payload))

    def __enqueueRaceMessage(self, message, channel, retries=RETRY_COUNT):
        logger.debug("RaceTransponder433: enqueueRaceMessage")
        messageData = RaceMessage(message, channel, self.currentSequenceId)
        chksum = 0x5B
        bytes_val = messageData.toBytes()
        for b in bytes_val:
            chksum = (chksum + b) & 0xFF
        chksum = (chksum + 0xFE) & 0xFF
        payload = pack('< BB 8s B B', 0xFC, 0x5B, bytes_val, 0xFE, chksum)
        self.__printPayload(payload)
        self.lock.acquire()
        for i in range(retries):
            self.raceMsgQueue.append(payload)
        self.lock.release()
        self.__incSeqId()
    
    def __enqueueRaceInfo(self, data, retries=RETRY_COUNT):
        logger.debug("RaceTransponder433: enqueueRaceInfo")
        intVal = data.toInt()
        chksum = 0x5A
        bytes_val = intVal.to_bytes(4, 'little')
        for b in bytes_val:
            chksum = (chksum + b) & 0xFF
        chksum = (chksum + 0xFE) & 0xFF
        payload = pack('< BB L B B', 0xFC, 0x5A, intVal, 0xFE, chksum)
        self.__printPayload(payload)
        self.lock.acquire()
        for i in range(retries):
            self.raceInfoQueue.append(payload)
        self.lock.release()

    def __enqueueRaceInfoReset(self):
        logger.debug("RaceTransponder433: enqueueRaceInfoReset")
        intVal = 0xFFFFFFFF
        chksum = 0x5A
        bytes_val = intVal.to_bytes(4, 'little')
        for b in bytes_val:
            chksum = (chksum + b) & 0xFF
        chksum = (chksum + 0xFE) & 0xFF
        payload = pack('< BB L B B', 0xFC, 0x5A, intVal, 0xFE, chksum)
        self.__printPayload(payload)
        self.lock.acquire()
        self.raceInfoQueue.append(payload)
        self.lock.release()

    def __sendRaceInfo(self, serial_port):
        self.lock.acquire()
        item = self.raceInfoQueue.pop(0)
        self.lock.release()
        logger.debug("RaceTransponder433: sendRaceInfo: " + str(item))
        serial_port.write(item)

    def __sendRaceMsg(self, serial_port):
        self.lock.acquire()
        item = self.raceMsgQueue.pop(0)
        self.lock.release()
        logger.debug("RaceTransponder433: sendRaceMsg: " + str(item))
        serial_port.write(item)

    def __buildPilotChannelsList(self):
        profile_id = self.racecontext.rhdata.get_option('currentProfile', None)
        logger.debug("RaceTransponder433: current profile_id: " + str(profile_id))

        profile = self.racecontext.rhdata.get_profile(profile_id)
        frequencies = json.loads(profile.frequencies)
        bands = frequencies['b']
        channels = frequencies['c']

        self.pilotChannels.clear()
        for i in range (0, len(bands)):
            band_channel = str(bands[i]) + str(channels[i])
            self.pilotChannels.append(band_channel)
            logger.debug("RaceTransponder433: profile channel: " + str(band_channel))

    def __generateRaceInfoMap(self):
        self.raceInfoMap.clear()
        for chn in self.pilotChannels:
            self.raceInfoMap[chn] = RaceInfo(0, 0, 0, 0, 0, CH_IDX[chn].value)

    def onStartup(self, _args):
        logger.debug("RaceTransponder433: onStartup")
        self.__discoverPort()
        if self.ready == True and self.serial_port_name:
            logger.info("RaceTransponder433: Starting communication thread")
            self.__startCommLoop()
        else:
            logger.warning("RaceTransponder433: No usable comm port, giving up...")

    def onRaceLapRecorded(self, args):
        logger.debug("RaceTransponder433: onRaceLapRecorded")

        if 'node_index' not in args:
            logger.error("RaceTransponder433: Failed to send results")
            return False
        
        # raceinfo
        # Get relevant results
        if 'gap_info' in args:
            info = args['gap_info']
        else:
            info = Results.get_gap_info(self.racecontext, args['node_index'])

        win_condition = info.race.win_condition
        if win_condition == WinCondition.FASTEST_3_CONSECUTIVE:
            logger.debug("RaceTransponder433: FASTEST_3_CONSECUTIVE")
            data = args['results']['by_consecutives']
        elif win_condition == WinCondition.FASTEST_LAP:
            logger.debug("RaceTransponder433: FASTEST_LAP")
            data = args['results']['by_fastest_lap']
        else:
            logger.debug("RaceTransponder433: by_race_time")
            # WinCondition.MOST_LAPS
            # WinCondition.FIRST_TO_LAP_X
            # WinCondition.NONE
            data = args['results']['by_race_time']

        for index, result in enumerate(data):
            raceInfoKey = self.pilotChannels[result['node']]
            logger.debug("RaceTransponder433: raceInfoKey=" + raceInfoKey)
            self.raceInfoMap[raceInfoKey].pos = index + 1
            self.raceInfoMap[raceInfoKey].lap = int(result['laps']) + 1
            self.raceInfoMap[raceInfoKey].started = int(result['starts'])
            if result['last_lap']: # 0:07.138
                last_lap_str = result['last_lap']
                logger.debug("RaceTransponder433: last_lap=" + last_lap_str)
                min_sec, hunds = last_lap_str.split('.')
                mins, secs = min_sec.split(':')
                secsTotal = int(mins) * 60 + int(secs)
                hundsTotal = int(int(hunds)/10)
                self.raceInfoMap[raceInfoKey].secs = secsTotal
                self.raceInfoMap[raceInfoKey].hunds = hundsTotal
                logger.debug("RaceTransponder433: " + raceInfoKey + " : " + str(self.raceInfoMap[raceInfoKey]))
        
        for retry in range(RETRY_COUNT):
            for key in self.pilotChannels:
                if key in self.raceInfoMap.keys():
                    self.__enqueueRaceInfo(self.raceInfoMap[key], 1)

        # delta
        if info.current.position > 1:
            logger.debug("RaceTransponder433: got delta")
            split_time = info.next_rank.split_time
            split_time_secs = int(split_time / 1000)
            split_time_hunds = int(split_time / 10) % 100
            chn_idx = CH_IDX[self.pilotChannels[int(args['node_index'])]].value
            self.__enqueueRaceMessage(" {:02d}.{:02d}".format(split_time_secs, split_time_hunds), chn_idx)
        else:
            logger.debug("RaceTransponder433: 1st position, no delta")

    def onHeatSet(self, _args):
        # nothing to do here
        logger.debug("RaceTransponder433: onHeatSet")

    def onRaceStage(self, _args):
        # race scheduled
        logger.debug("RaceTransponder433: onRaceStage")
        self.__enqueueRaceMessage(" ARM  ", CH_IDX.BROADCAST.value)

        self.__buildPilotChannelsList()
        self.__generateRaceInfoMap()

    def onRaceStart(self, _args):
        # race started
        logger.debug("RaceTransponder433: onRaceStart")
        logger.info("Race started!")
        self.__enqueueRaceMessage(" GO!  ", CH_IDX.BROADCAST.value)

    def onRaceFinish(self, _args):
        # race finished
        logger.debug("RaceTransponder433: onRaceFinish")
        logger.info("Race finished!")
        self.__enqueueRaceMessage("FINISH", CH_IDX.BROADCAST.value)

    def onRaceStop(self, _args):
        # race stopped by manager
        logger.debug("RaceTransponder433: onRaceStop")
        logger.info("Race stopped!")
        self.__enqueueRaceMessage(" STOP ", CH_IDX.BROADCAST.value)
        self.__enqueueRaceInfoReset()
