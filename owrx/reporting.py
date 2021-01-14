import threading
from abc import ABC, abstractmethod
from owrx.config import Config


class Reporter(ABC):
    @abstractmethod
    def stop(self):
        pass

    @abstractmethod
    def spot(self, spot):
        pass

    @abstractmethod
    def getSupportedModes(self):
        return []


class ReportingEngine(object):
    creationLock = threading.Lock()
    sharedInstance = None

    @staticmethod
    def getSharedInstance():
        with ReportingEngine.creationLock:
            if ReportingEngine.sharedInstance is None:
                ReportingEngine.sharedInstance = ReportingEngine()
            return ReportingEngine.sharedInstance

    @staticmethod
    def stopAll():
        with ReportingEngine.creationLock:
            if ReportingEngine.sharedInstance is not None:
                ReportingEngine.sharedInstance.stop()

    def __init__(self):
        self.reporters = []
        if Config.get()["pskreporter_enabled"]:
            # inline import due to circular dependencies
            from owrx.pskreporter import PskReporter
            self.reporters += [PskReporter()]

    def stop(self):
        for r in self.reporters:
            r.stop()

    def spot(self, spot):
        for r in self.reporters:
            if spot["mode"] in r.getSupportedModes():
                r.spot(spot)
