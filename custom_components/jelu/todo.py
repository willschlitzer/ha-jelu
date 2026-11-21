"""To-do list of the books being read in Jelu."""

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ReadingEvent, ReadingEventType
from .const import DOMAIN
from .coordinator import JeluConfigEntry, JeluDataUpdateCoordinator
from .entity import JeluEntity

# Writes go through the coordinator one at a time anyway; don't let HA queue them in parallel.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JeluConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Jelu to-do list from a config entry."""
    async_add_entities([JeluCurrentlyReadingTodoList(entry.runtime_data)])


def describe_progress(book: ReadingEvent) -> str:
    """Describe a book's authors and progress, e.g. "Pierce Brown · 45% (page 270 of 600)"."""
    parts = []
    if book.authors:
        parts.append(", ".join(book.authors))
    if book.current_page and book.page_count:
        parts.append(
            f"{book.percent_read or 0}% (page {book.current_page} of {book.page_count})"
        )
    elif book.percent_read:
        parts.append(f"{book.percent_read}%")
    elif book.current_page:
        parts.append(f"page {book.current_page}")
    return " · ".join(parts)


class JeluCurrentlyReadingTodoList(JeluEntity, TodoListEntity):
    """The books being read, as a to-do list. Checking a book off marks it finished."""

    _attr_translation_key = "currently_reading"
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM

    def __init__(self, coordinator: JeluDataUpdateCoordinator) -> None:
        """Set up the to-do list."""
        super().__init__(coordinator, "currently_reading_todo")
        self._attr_todo_items = self._build_items()

    def _build_items(self) -> list[TodoItem]:
        return [
            TodoItem(
                uid=book.user_book_id,
                summary=book.title,
                description=describe_progress(book) or None,
                status=TodoItemStatus.NEEDS_ACTION,
            )
            for book in self.coordinator.data.currently_reading
        ]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Rebuild the items when new data arrives."""
        self._attr_todo_items = self._build_items()
        super()._handle_coordinator_update()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Mark a book finished when it is checked off. Nothing else can be changed here."""
        book = next(
            (
                book
                for book in self.coordinator.data.currently_reading
                if book.user_book_id == item.uid
            ),
            None,
        )
        if book is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="book_not_found",
                translation_placeholders={
                    "book": item.summary or str(item.uid),
                    "books": ", ".join(
                        b.title for b in self.coordinator.data.currently_reading
                    )
                    or "none",
                },
            )
        if item.status != TodoItemStatus.COMPLETED:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="todo_only_complete"
            )
        await self.coordinator.async_set_reading_status(book, ReadingEventType.FINISHED)
