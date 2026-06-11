
import time

class AuditLogger:
    def __init__(self, db):
        self.db = db

    def log(self, event_type, details):
        """Log a security event."""
        print(f"[AUDIT] {event_type}: {details}")
        if self.db:
            try:
                self.db.add_audit_log(event_type, details)
            except Exception as e:
                print(f"[ERROR] Failed to write audit log: {e}")

# Global logger instance will be initialized in main app
_logger = None

def init_logger(db):
    global _logger
    _logger = AuditLogger(db)

def get_logger():
    return _logger
