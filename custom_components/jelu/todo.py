"""The "Currently reading" to-do list.

Each book being read is one open to-do item. Checking an item off marks the book finished in
Jelu; after the refresh that follows, the book is no longer "currently reading" and drops off
the list. No other edits are allowed (adding, renaming, deleting); those belong in Jelu.

HA calls async_setup_entry() here because "todo" is listed in PLATFORMS in __init__.py.
"""

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

# How many changes HA may send to this platform at once. 1 = one at a time, so checking off
# two books quickly sends two requests in turn rather than together.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JeluConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the to-do list for one Jelu server."""
    async_add_entities([JeluCurrentlyReadingTodoList(entry.runtime_data)])


def describe_progress(book: ReadingEvent) -> str:
    """Describe a book's authors and progress, e.g. "Pierce Brown · 45% (page 270 of 600)".

    Shows what Jelu knows: page and percent, only percent, only a page, or just the authors.
    """
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

    # Name ("Currently reading") from translations/en.json, under entity → todo.
    _attr_translation_key = "currently_reading"
    # Which edits HA's UI offers. Only updating an item, which is how checking it off arrives;
    # no adding, deleting or reordering.
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM

    def __init__(self, coordinator: JeluDataUpdateCoordinator) -> None:
        """Set up the to-do list with the books from the first poll."""
        super().__init__(coordinator, "currently_reading_todo")
        self._attr_todo_items = self._build_items()

    def _build_items(self) -> list[TodoItem]:
        """Turn the coordinator's books into to-do items."""
        return [
            TodoItem(
                # The item's ID. HA passes it back when the item is changed, which is how
                # async_update_todo_item knows which book was checked off.
                uid=book.user_book_id,
                summary=book.title,
                description=describe_progress(book) or None,
                status=TodoItemStatus.NEEDS_ACTION,
            )
            for book in self.coordinator.data.currently_reading
        ]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Rebuild the items whenever the coordinator has new data.

        CoordinatorEntity calls this after every poll. Sensors don't need it because their
        properties read the data directly; a to-do list keeps its items in a list, so the
        list is rebuilt here before the parent class redraws the entity.
        """
        self._attr_todo_items = self._build_items()
        super()._handle_coordinator_update()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Handle a change to an item: checking it off finishes the book.

        HA calls this with the item as it should now be. Only a change of status to
        "completed" is acted on; any other change is refused with an explanation.
        """
        book = next(
            (
                book
                for book in self.coordinator.data.currently_reading
                if book.user_book_id == item.uid
            ),
            None,
        )
        if book is None:
            # The list was out of date, e.g. the book was finished in Jelu since the last poll.
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
        # The coordinator sends the change to Jelu, reports errors, and refreshes the data.
        await self.coordinator.async_set_reading_status(book, ReadingEventType.FINISHED)
