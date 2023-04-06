from owrx.config import Config
from owrx.property import PropertyManager, PropertyDeleted, PropertyDelegator, PropertyLayer, PropertyReadOnly
from owrx.feature import FeatureDetector, UnknownFeatureException
from owrx.source import SdrSource, SdrSourceEventClient
from functools import partial

import logging

logger = logging.getLogger(__name__)


class MappedSdrSources(PropertyDelegator):
    def __init__(self, pm: PropertyManager):
        super().__init__(PropertyLayer())
        for key, value in pm.items():
            self._addSource(key, value)
        pm.wire(self.handleSdrDeviceChange)

    def handleSdrDeviceChange(self, changes):
        for key, value in changes.items():
            if value is PropertyDeleted:
                if key in self:
                    del self[key]
            else:
                if key not in self:
                    self._addSource(key, value)

    def handleDeviceUpdate(self, key, value, *args):
        if key not in self and self.isDeviceValid(value):
            self[key] = self.buildNewSource(key, value)
        elif key in self and not self.isDeviceValid(value):
            del self[key]

    def _addSource(self, key, value):
        self.handleDeviceUpdate(key, value)

    def isDeviceValid(self, device):
        return self._sdrTypeAvailable(device)

    def _sdrTypeAvailable(self, value):
        featureDetector = FeatureDetector()
        try:
            if not featureDetector.is_available(value["type"]):
                logger.error(
                    'The SDR source type "{0}" is not available. please check the feature report for details.'.format(
                        value["type"]
                    )
                )
                return False
            return True
        except UnknownFeatureException:
            logger.error(
                'The SDR source type "{0}" is invalid. Please check your configuration'.format(value["type"])
            )
            return False

    def buildNewSource(self, id, props):
        sdrType = props["type"]
        className = "".join(x for x in sdrType.title() if x.isalnum()) + "Source"
        module = __import__("owrx.source.{0}".format(sdrType), fromlist=[className])
        cls = getattr(module, className)
        return cls(id, props)

    def _removeSource(self, key, source):
        source.shutdown()

    def __setitem__(self, key, value):
        source = self[key] if key in self else None
        if source is value:
            return
        super().__setitem__(key, value)
        if source is not None:
            self._removeSource(key, source)

    def __delitem__(self, key):
        source = self[key] if key in self else None
        super().__delitem__(key)
        if source is not None:
            self._removeSource(key, source)


class SourceStateHandler(SdrSourceEventClient):
    def __init__(self, pm, key, source: SdrSource):
        self.pm = pm
        self.key = key
        self.source = source

    def selfDestruct(self):
        self.source.removeClient(self)

    def onFail(self):
        del self.pm[self.key]

    def onDisable(self):
        del self.pm[self.key]

    def onEnable(self):
        self.pm[self.key] = self.source

    def onShutdown(self):
        del self.pm[self.key]


class ActiveSdrSources(PropertyReadOnly):
    def __init__(self, pm: PropertyManager):
        self.handlers = {}
        self._layer = PropertyLayer()
        super().__init__(self._layer)
        for key, value in pm.items():
            self._addSource(key, value)
        pm.wire(self.handleSdrDeviceChange)

    def handleSdrDeviceChange(self, changes):
        for key, value in changes.items():
            if value is PropertyDeleted:
                self._removeSource(key)
            else:
                self._addSource(key, value)

    def isAvailable(self, source: SdrSource):
        return source.isEnabled() and not source.isFailed()

    def _addSource(self, key, source: SdrSource):
        if self.isAvailable(source):
            self._layer[key] = source
        self.handlers[key] = SourceStateHandler(self._layer, key, source)
        source.addClient(self.handlers[key])

    def _removeSource(self, key):
        self.handlers[key].selfDestruct()
        del self.handlers[key]
        if key in self._layer:
            del self._layer[key]


class AvailableProfiles(PropertyReadOnly):
    def __init__(self, pm: PropertyManager):
        self.subscriptions = {}
        self.profileSubscriptions = {}
        self._layer = PropertyLayer()
        super().__init__(self._layer)
        for key, value in pm.items():
            self._addSource(key, value)
        pm.wire(self.handleSdrDeviceChange)

    def handleSdrDeviceChange(self, changes):
        for key, value in changes.items():
            if value is PropertyDeleted:
                self._removeSource(key)
            else:
                self._addSource(key, value)

    def handleSdrNameChange(self, s_id, source, name):
        self._layer[s_id] = name

    def _addSource(self, key, source: SdrSource):
        self._layer["{}".format(key)] = source.getName()
        self.subscriptions[key] = [
            source.getProps().wireProperty("name", partial(self.handleSdrNameChange, key, source)),
        ]

    def _removeSource(self, key):
        del self._layer[key]
        if key in self.subscriptions:
            while self.subscriptions[key]:
                self.subscriptions[key].pop().cancel()
            del self.subscriptions[key]

class SdrService(object):
    sources = None
    activeSources = None
    availableProfiles = None

    @staticmethod
    def getFirstSource():
        sources = SdrService.getActiveSources()
        if not sources:
            return None
        # TODO: configure default sdr in config? right now it will pick the first one off the list.
        return sources[list(sources.keys())[0]]

    @staticmethod
    def getSource(id):
        sources = SdrService.getActiveSources()
        if not sources:
            return None
        if id not in sources:
            return None
        return sources[id]

    @staticmethod
    def getAllSources():
        if SdrService.sources is None:
            SdrService.sources = MappedSdrSources(Config.get()["sdrs"])
        return SdrService.sources

    @staticmethod
    def getActiveSources():
        if SdrService.activeSources is None:
            SdrService.activeSources = ActiveSdrSources(SdrService.getAllSources())
        return SdrService.activeSources

    @staticmethod
    def getAvailableProfiles():
        if SdrService.availableProfiles is None:
            SdrService.availableProfiles = AvailableProfiles(SdrService.getActiveSources())
        return SdrService.availableProfiles

    @staticmethod
    def stopAllSources():
        for source in SdrService.getAllSources().values():
            source.stop()
