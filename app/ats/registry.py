from app.ats.base import BaseATSAdapter

class AdapterRegistry:
    def __init__(self): self.adapters = {}

    def register(self, name, adapter):
        if not name or not issubclass(adapter, BaseATSAdapter):
            raise ValueError("Register a named BaseATSAdapter subclass")
        self.adapters[name] = adapter

    def create(self, name, worker):
        adapter = self.adapters.get(name)
        if adapter is None:
            raise ValueError(f"Unsupported platform: {name}")
        return adapter(worker)
