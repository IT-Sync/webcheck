def site_status_callback(site_id: int) -> str:
    return f"st:{int(site_id)}"


def site_delete_callback(site_id: int) -> str:
    return f"del:{int(site_id)}"


def site_pause_callback(site_id: int) -> str:
    return f"pause:{int(site_id)}"


def site_resume_callback(site_id: int) -> str:
    return f"resume:{int(site_id)}"


def admin_delete_callback(site_id: int) -> str:
    return f"ad:{int(site_id)}"
