from app.domain.enums import FieldType as T, InspectionStatus as I
from app.services.option_collector import OptionCollector

class FieldInspectionService:
    def __init__(self, collector: OptionCollector): self.collector = collector

    async def inspect(self, field, adapter, target: str | None = None):
        if field.field_type == T.UNKNOWN:
            field.inspection_status = I.HUMAN_REQUIRED
            return field
        if field.field_type not in {T.SELECT, T.AUTOCOMPLETE, T.MULTISELECT} or (field.options and field.field_type in {T.SELECT, T.MULTISELECT}):
            field.inspection_status = I.INSPECTED
            return field
        try:
            await adapter.open_control(field)
            if field.locator.searchable and target:
                await adapter.search_options(field, target)
                field.options = await adapter.visible_options(field)
            elif field.locator.virtualized:
                field.options = await self.collector.collect(
                    lambda: adapter.visible_options(field), lambda: adapter.scroll_options(field))
            else:
                field.options = await adapter.visible_options(field)
            field.inspection_status = I.INSPECTED if field.options else I.HUMAN_REQUIRED
        except Exception:
            field.inspection_status = I.HUMAN_REQUIRED
        finally:
            await adapter.close_control(field)
        return field
