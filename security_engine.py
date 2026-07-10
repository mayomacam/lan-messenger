
import time
import audit

class SecurityEngine:
    def __init__(self, db, block_threshold=5, timeframe=3600):
        self.db = db
        self.block_threshold = block_threshold
        self.timeframe = timeframe

    def report_incident(self, ip, event_type, details):
        """Report a security incident and check for auto-blocking."""
        logger = audit.get_logger()
        if logger:
            logger.log(event_type, details, ip_address=ip)

        if not ip:
            return

        # Check if we should block this IP
        incident_count = self.db.get_incident_count(ip, self.timeframe)
        if incident_count >= self.block_threshold:
            self._block_ip(ip)

    def _block_ip(self, ip):
        """Automatically block an IP."""
        perms = self.db.get_peer_permissions(ip)
        if not perms.get('is_blocked'):
            perms['is_blocked'] = 1
            self.db.update_peer_permissions(ip, perms)
            logger = audit.get_logger()
            if logger:
                logger.log("IPS_AUTO_BLOCK", f"Automatically blocked IP {ip} due to excessive security incidents.", ip_address=ip)
            print(f"[SECURITY] Auto-blocked IP: {ip}")

_engine = None

def init_engine(db):
    global _engine
    _engine = SecurityEngine(db)

def get_engine():
    return _engine
