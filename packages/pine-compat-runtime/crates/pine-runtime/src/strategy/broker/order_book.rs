use super::pending_entries::PendingEntryBook;
use super::pending_exits::PendingExitBook;

#[derive(Debug, Clone, PartialEq)]
pub(super) struct OrderBook {
    entries: PendingEntryBook,
    exits: PendingExitBook,
}

impl OrderBook {
    pub(super) fn new() -> Self {
        Self {
            entries: PendingEntryBook::new(),
            exits: PendingExitBook::new(),
        }
    }

    pub(super) fn entries(&self) -> &PendingEntryBook {
        &self.entries
    }

    pub(super) fn entries_mut(&mut self) -> &mut PendingEntryBook {
        &mut self.entries
    }

    pub(super) fn exits(&self) -> &PendingExitBook {
        &self.exits
    }

    pub(super) fn exits_mut(&mut self) -> &mut PendingExitBook {
        &mut self.exits
    }

    pub(super) fn cancel_id(&mut self, id: &str) {
        self.entries.cancel_id(id);
        self.exits.cancel_id(id);
    }

    pub(super) fn clear_all(&mut self) {
        self.entries.clear_all();
        self.exits.clear_all();
    }
}

impl Default for OrderBook {
    fn default() -> Self {
        Self::new()
    }
}
