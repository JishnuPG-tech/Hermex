)
    return {
        "uuid": mid,
        "text": text,
        "sender": sender,
        "index": idx,
        "created_at": now,
        "updated_at": now,
        "content": [{"type": "text", "text": text}],
        "attachments": [],
        "files": [],
        "parent_message_uuid": prev_uuid,
        "stop_reason": "end_turn" if sender == "assistant" else None,
        "stop_sequence": None,
        "truncated": False
    }

def _build_conv_response(conv: Dict[str, Any]) -> Dict[str, Any]:
    msgs = conv.get("chat_messages", [])
    leaf_uuid = msgs[-1]["uuid"] if msgs else None
    return {
        "uuid": conv.get("uuid"),
        "name": conv.get("name", "Chat"),
        "summary": conv.get("summary") or conv.get("name", "Chat"),
        "created_at": conv.get("created_at"),
        "updated_at": conv.get("updated_at"),
        "settings": {
            "preview_feature_uses_artifacts": False,
            "model": "hermes-agent"
        },
        "is_starred": conv.get("is_starred", False),
        "current_leaf_message_uuid": leaf_uuid,
        "chat_messages": msgs,
        "model": "hermes-agent"
    }

# 1. Models Catalog (Full ModelOption array matching Organization.claude_ai_bootstrap_models_config)
MODELS_CATALOG = [
    {
        "model": "claude-3-5-sonnet-20241022",
        "id": "claude-3-5-sonnet-20241022",
        "name": "Sonnet 5",
        "display_name": "Sonnet 5",
        "short_name": "Sonnet 5 Low",
        "description": {"text": "Most efficient for everyday tasks"},
        "description_i18n_key": None,
        "overflow": None,
        "inactive": False,
        "thinking_modes": [],
        "capabilities": {
            "mm_images": True,
            "mm_pdf": True,
            "web_search": True,
            "code_execution": True
        },
        "notice_text": None,
        "notice_text_i18n_key": None,
        "knowledgeCutoff": "2024-10-22",
        "slow_kb_warning_threshold": None,
        "created_at": "2024-10-22T00:00:00Z",
        "type": "model"
    },
    {
        "model": "claude-3-5-haiku-20241022",
        "id": "claude-3-5-haiku-20241022",
        "name": "Haiku 4.5",
        "display_name": "Haiku 4.5",
        "short_name": "Haiku 4.5",
        "description": {"text": "Fastest for quick answers"},
        "description_i18n_key": None,
        "overflow": None,
        "inactive": False,
        "thinking_modes": [],
        "capabilities": {
            "mm_images": True,
            "mm_pdf": True,
            "web_search": True,
            "code_execution": True
        },
        "notice_text": None,
        "notice_text_i18n_key": None,
        "knowledgeCutoff": "2024-10-22",
        "slow_kb_warning_threshold": None,
        "created_at": "2024-10-22T00:00:00Z",
        "type": "model"
    },
    {
        "model": "claude-3-opus-20240229",
        "id": "claude-3-opus-20240229",
        "name": "Opus 5",
        "display_name": "Opus 5",
        "short_name": "Opus 5",
        "description": {"text": "For complex tasks"},
        "description_i18n_key": None,
        "overflow": None,
        "inactive": False,
        "thinking_modes": [],
        "capabilities": {
            "mm_images": True,
            "mm_pdf": True,
            "web_search": True,
            "code_execution": True
        },
        "notice_text": None,
        "notice_text_i18n_key": None,
        "knowledgeCutoff": "2024-02-29",
        "slow_kb_warning_threshold": None,
        "created_at": "2024-02-29T00:00:00Z",
        "type": "model"
    },
    {
        "model": "hermes-agent",
        "id": "hermes-agent",
        "name": "Fable 5",
        "display_name": "Fable 5",
        "short_name": "Fable 5",
        "description": {"text": "For your toughest challenges"},
        "description_i18n_key": None,
        "overflow": None,
        "inactive": False,
        "thinking_modes": [],
        "capabilities": {
            "mm_images": True,
            "mm_pdf": True,
            "web_search": True,
            "code_execution": True
        },
        "notice_text": None,
        "notice_text_i18n_key": None,
        "knowledgeCutoff": "2026-01-01",
        "slow_kb_warning_threshold": None,
        "created_at": "2026-01-01T00:00:00Z",
        "type": "model"
    }
]

DEFAULT_THINKING_OPTIONS = {
    "effort_options": [
        {"id": "low", "name": "Low", "description": "Quick reasoning", "recommended": False},
        {"id": "medium", "name": "Medium", "description": "Balanced reasoning", "recommended": True},
        {"id": "high", "name": "High", "description": "Deep thinking", "recommended": False},
        {"id": "max", "name": "Max", "description": "Maximum reasoning effort", "recommended": False}
    ],
    "mode_options": [
        {"id": "off", "name": "Off", "description": "Direct response without thinking", "recommended": False},
        {"id": "auto", "name": "Auto", "description": "Let Hermes decide when to think", "recommended": True},
        {"id": "on", "name": "Always On", "description": "Always think before answering", "recommended": False}
    ]
}

# Exact ModelSelectorConfig List expected by Kotlin kotlinx.serialization in AppStartResponse
MODEL_SELECTOR_CONFIG_LIST = [
    {
        "id": "chat",
        "models": [
            {
                "id": "claude-3-5-sonnet-20241022",
                "name": "Sonnet 5",
                "short_name": "Sonnet 5 Low",
                "voice_model": None,
                "description": {"english": "Most efficient for everyday tasks"},
                "notice": None,
                "selection_notice": None,
                "section": "main",
                "disabled": False,
                "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
                "thinking": DEFAULT_THINKING_OPTIONS,
                "badge": None
            },
            {
                "id": "claude-3-5-haiku-20241022",
                "name": "Haiku 4.5",
                "short_name": "Haiku 4.5",
                "voice_model": None,
                "description": {"english": "Fastest for quick answers"},
                "notice": None,
                "selection_notice": None,
                "section": "main",
                "disabled": False,
                "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
                "thinking": DEFAULT_THINKING_OPTIONS,
                "badge": None
            },
            {
                "id": "claude-3-opus-20240229",
                "name": "Opus 5",
                "short_name": "Opus 5",
                "voice_model": None,
                "description": {"english": "For complex tasks"},
                "notice": None,
                "selection_notice": None,
                "section": "main",
                "disabled": False,
                "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
                "thinking": DEFAULT_THINKING_OPTIONS,
                "badge": {"message": {"english": "Pro"}}
            },
            {
                "id": "hermes-agent",
                "name": "Fable 5",
                "short_name": "Fable 5",
                "voice_model": None,
                "description": {"english": "For your toughest challenges"},
                "notice": None,
                "selection_notice": None,
                "section": "main",
                "disabled": False,
                "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
                "thinking": DEFAULT_THINKING_OPTIONS,
                "badge": {"message": {"english": "Pro"}}
            }
        ]
    },
    {
        "id": "voice",
        "models": [
            {
                "id": "claude-3-5-sonnet-20241022",
                "name": "Sonnet 5",
                "short_name": "Sonnet 5 Low",
                "voice_model": None,
                "description": None,
                "notice": None,
                "selection_notice": None,
                "section": "main",
                "disabled": False,
                "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
                "thinking": None,
                "badge": None
            },
            {
                "id": "claude-3-5-haiku-20241022",
                "name": "Haiku 4.5",
                "short_name": "Haiku 4.5",
                "voice_model": None,
                "description": None,
                "notice": None,
                "selection_notice": None,
                "section": "main",
                "disabled": False,
                "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
                "thinking": None,
                "badge": None
            }
        ]
    }
]

MODEL_SELECTOR_STATE_LIST = [
    {
        "id": "chat",
        "model": "hermes-agent",
        "thinking": {
            "mode": "off",
            "effort": "low"
        },
        "thinking_by_model": []
    },
    {
        "id": "voice",
        "model": "claude-3-5-sonnet-20241022",
        "thinking": None,
        "thinking_by_model": []
    }
]

USER_OBJ = {
    "id": "usr_0123456789abcdef",
    "email": "jishnupg2005@gmail.com",
    "name": "Jishnu (Admin Max)",
    "avatar_url": None
}

ORG_OBJ = {
    "id": "org_0123456789abcdef",
    "uuid": "org_0123456789abcdef",
    "name": "Hermes Admin Max Team",
    "settings": {"billing_tier": "default"},
    "capabilities": [
        "chat",
        "claude_pro",
        "claude_max",
        "raven",
        "artifacts",
        "projects",
        "custom_connectors",
        "voice",
        "mcp"
    ],
    "claude_ai_bootstrap_models_config": MODELS_CATALOG,
    "raven_type": None,
    "rate_limit_tier": "claude_max",
    "billing_type": "stripe",
    "rate_limit_upsell": None,
    "subscription_pause": "ABSENT"
}

ACCOUNT_OBJ = {
    "uuid": "usr_0123456789abcdef",
    "email_address": "jishnupg2005@gmail.com",
    "full_name": "Jishnu (Admin Max)",
    "memberships": [
        {
            "organization": ORG_OBJ,
            "role": "admin"
        }
    ]
}

@router.get("/v1/models")
@router.get("/models")
@router.get("/api/v1/models")
@router.get("/api/models")
@router.get("/hermes/v1/models")
async def list_models():
    first_key = MODELS_CATALOG[0].get("model") or MODELS_CATALOG[0].get("id")
    last_key = MODELS_CATALOG[-1].get("model") or MODELS_CATALOG[-1].get("id")
    return {
        "data": MODELS_CATALOG,
        "has_more": False,
        "first_id": first_key,
        "last_id": last_key
    }

def _resolve_account(authorization: Optional[str] = None) -> Dict[str, Any]:
    if authorization:
        from gateway.auth_api import decode_session_token
        payload = decode_session_token(authorization)
        if payload:
            uid = payload.get("sub", "usr_0123456789abcdef")
            email = payload.get("email", "jishnupg2005@gmail.com")
            name = payload.get("name", "Jishnu (Admin Max)")
            is_super_admin = email in {"jishnupg2005@gmail.com", "jishnu.pg@gmail.com"}
            return {
                "uuid": uid,
                "email_address": email,
                "full_name": name,
                "memberships": [
                    {
                        "organization": {
                            "id": f"org_{uid[:16]}",
                            "uuid": f"org_{uid[:16]}",
                            "name": f"{name}'s Admin Org" if is_super_admin else f"{name}'s Organization",
                            "settings": {"billing_tier": "default"},
                            "capabilities": [
                                "chat",
                                "claude_pro",
                                "claude_max",
                                "raven",
                                "artifacts",
                                "projects",
                                "custom_connectors",
                                "voice",
                                "mcp"
                            ],
                            "claude_ai_bootstrap_models_config": MODELS_CATALOG,
                            "raven_type": None,
                            "rate_limit_tier": "claude_max",
                            "billing_type": "stripe",
                            "rate_limit_upsell": None,
                            "subscription_pause": "ABSENT"
                        },
                        "role": "admin"
                    }
                ]
            }
    return ACCOUNT_OBJ

# 2. Account Profile
@router.get("/api/account")
@router.get("/account")
@router.get("/hermes/api/account")
@router.get("/hermes/account")
async def get_account(authorization: Optional[str] = Header(None)):
    return _resolve_account(authorization)

# 3. App Start & Bootstrap
@router.get("/api/account/app_start")
@router.get("/account/app_start")
@router.get("/api/bootstrap")
@router.get("/bootstrap")
@router.get("/api/bootstrap/{org_id}/app_start")
@router.get("/bootstrap/{org_id}/app_start")
@router.get("/hermes/api/account/app_start")
@router.get("/hermes/api/bootstrap")
@router.get("/hermes/account/app_start")
@router.get("/hermes/bootstrap")
async def app_start_response(org_id: Optional[str] = None, authorization: Optional[str] = Header(None)):
    current_account = _resolve_account(authorization)
    email_str = current_account.get("email_address") or "jishnupg2005@gmail.com"
    name_str = current_account.get("full_name") or "Jishnu (Admin Max)"
    uid_str = current_account.get("uuid") or "usr_0123456789abcdef"
    
    return {
        "account": current_account,
        "user": {
            "id": uid_str,
            "uuid": uid_str,
            "email": email_str,
            "email_address": email_str,
            "name": name_str,
            "full_name": name_str,
            "display_name": name_str,
            "avatar_url": None
        },
        "organization": ORG_OBJ,
        "model_selector_config": MODEL_SELECTOR_CONFIG_LIST,
        "model_selector_state": MODEL_SELECTOR_STATE_LIST,
        "org_growthbook": {
            "features": {
                "model_selector_enabled": {"defaultValue": True},
                "pro_enabled": {"defaultValue": True},
                "premium_enabled": {"defaultValue": True},
                "subscription_active": {"defaultValue": True},
                "mobile_deedee_config": {
                    "defaultValue": {
                        "speech_input": {
                            "maximum_request_duration_seconds": 300,
                            "default_language_code": "en-US",
                            "supported_languages": [
                                {
                                    "code": "en-US",
                                    "display_name": "English (US)",
                                    "voices": [
                                        {"id": "voice_1", "display_name": "Hermes Natural", "preview_url": None},
                                        {"id": "voice_2", "display_name": "Hermes Classic", "preview_url": None}
                                    ]
                                }
                            ],
                            "is_voice_multilingual_enabled": True,
                            "is_language_beta": False
                        }
                    }
                }
            }
        },
        "server_localizations": {},
        "current_user_access": {
            "features": [
                {"feature": "web_search", "status": "available"},
                {"feature": "saffron", "status": "available"},
                {"feature": "wiggle", "status": "available"},
                {"feature": "dittos", "status": "available"},
                {"feature": "chat", "status": "available"},
                {"feature": "claude_code_web", "status": "available"},
                {"feature": "claude_code_desktop_auto_permissions", "status": "available"},
                {"feature": "public_projects", "status": "available"},
                {"feature": "conversation_preferences", "status": "available"},
                {"feature": "conversation_search", "status": "available"},
                {"feature": "dramatic_shrimp", "status": "available"},
                {"feature": "third_party_analytics", "status": "available"},
                {"feature": "voice", "status": "available"},
                {"feature": "tts", "status": "available"},
                {"feature": "speech_input", "status": "available"},
                {"feature": "read_aloud", "status": "available"},
                {"feature": "bell", "status": "available"}
            ],
            "account_features": [
                {"feature": "web_search", "status": "available"},
                {"feature": "chat", "status": "available"},
                {"feature": "claude_code_web", "status": "available"},
                {"feature": "voice", "status": "available"},
                {"feature": "tts", "status": "available"},
                {"feature": "speech_input", "status": "available"},
                {"feature": "read_aloud", "status": "available"},
                {"feature": "bell", "status": "available"}
            ]
        },
        "personalized_greeting": [],
        "statsig": {"flags": {}, "experiments": {}},
        "active_flags": ["claude_3_5_sonnet", "claude_3_opus", "artifacts", "memory", "latex", "model_selector_enabled", "pro_enabled", "premium_enabled", "voice", "speech_input", "tts", "read_aloud", "bell"],
        "flags": {
            "model_selector_enabled": True,
            "pro_enabled": True,
            "premium_enabled": True,
            "subscription_active": True,
            "voice": True,
            "tts": True,
            "speech_input": True,
            "read_aloud": True,
            "bell": True
        }
    }

# 4. Model Selector State (Surface switching)
@router.get("/api/organizations/{org_id}/model_selector_state/{surface}")
@router.get("/organizations/{org_id}/model_selector_state/{surface}")
@router.get("/hermes/api/organizations/{org_id}/model_selector_state/{surface}")
@router.get("/hermes/organizations/{org_id}/model_selector_state/{surface}")
async def get_surface_model_state(org_id: str, surface: str):
    for st in MODEL_SELECTOR_STATE_LIST:
        if st["id"] == surface:
            return st
    return {
        "id": surface,
        "surface": surface,
        "model": "claude-3-5-sonnet-20241022",
        "thinking": None,
        "thinking_by_model": []
    }

@router.post("/api/organizations/{org_id}/model_selector_state/{surface}")
@router.post("/organizations/{org_id}/model_selector_state/{surface}")
@router.post("/hermes/api/organizations/{org_id}/model_selector_state/{surface}")
@router.post("/hermes/organizations/{org_id}/model_selector_state/{surface}")
async def set_surface_model_state(org_id: str, surface: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    model = body.get("model")
    thinking = body.get("thinking")
    for st in MODEL_SELECTOR_STATE_LIST:
        if st["id"] == surface:
            if model:
                st["model"] = model
            if thinking is not None:
                st["thinking"] = thinking
            return st
    new_st = {
        "id": surface,
        "surface": surface,
        "model": model or "hermes-agent",
        "thinking": thinking or {"mode": "auto", "effort": "high"},
        "thinking_by_model": []
    }
    MODEL_SELECTOR_STATE_LIST.append(new_st)
    return new_st

# 5. Legal & Org Settings
@router.get("/api/legal")
@router.get("/legal")
@router.get("/hermes/api/legal")
@router.get("/hermes/legal")
async def get_legal():
    return {"status": "accepted", "acknowledged": True}

@router.get("/api/organizations/{org_id}/memory/settings")
@router.get("/organizations/{org_id}/memory/settings")
@router.get("/hermes/api/organizations/{org_id}/memory/settings")
@router.get("/hermes/organizations/{org_id}/memory/settings")
async def memory_settings(org_id: str):
    return {
        "enabled": True,
        "memory_enabled": True,
        "storage_type": "sqlite_wal"
    }

# 5. Live Notifications Dispatcher (FCM Device Push + Telegram Real-time Push)
_FCM_DEVICE_TOKENS = set()
FCM_SERVER_KEY = os.getenv("FCM_SERVER_KEY", "").strip()

@router.post("/api/organizations/{org_id}/notification/channels")
@router.post("/organizations/{org_id}/notification/channels")
@router.post("/hermes/api/organizations/{org_id}/notification/channels")
@router.post("/hermes/organizations/{org_id}/notification/channels")
@router.post("/api/notification/channels")
@router.post("/notification/channels")
@router.post("/hermes/api/notification/channels")
@router.post("/hermes/notification/channels")
@router.post("/api/organizations/{org_id}/notifications/channels")
@router.post("/organizations/{org_id}/notifications/channels")
@router.post("/hermes/api/organizations/{org_id}/notifications/channels")
@router.post("/hermes/organizations/{org_id}/notifications/channels")
@router.post("/api/organizations/{org_id}/devices")
@router.post("/organizations/{org_id}/devices")
@router.patch("/api/organizations/{org_id}/notification/preferences")
@router.patch("/organizations/{org_id}/notification/preferences")
@router.patch("/hermes/api/organizations/{org_id}/notification/preferences")
@router.patch("/hermes/organizations/{org_id}/notification/preferences")
@router.patch("/api/organizations/{org_id}/notification_preferences")
@router.patch("/organizations/{org_id}/notification_preferences")
@router.patch("/hermes/api/organizations/{org_id}/notification_preferences")
@router.patch("/hermes/organizations/{org_id}/notification_preferences")
@router.put("/api/organizations/{org_id}/notification/preferences")
@router.put("/organizations/{org_id}/notification/preferences")
@router.put("/hermes/api/organizations/{org_id}/notification/preferences")
@router.put("/hermes/organizations/{org_id}/notification/preferences")
@router.put("/api/organizations/{org_id}/notification_preferences")
@router.put("/organizations/{org_id}/notification_preferences")
@router.put("/hermes/api/organizations/{org_id}/notification_preferences")
@router.put("/hermes/organizations/{org_id}/notification_preferences")
@router.post("/api/organizations/{org_id}/notification/preferences")
@router.post("/organizations/{org_id}/notification/preferences")
@router.post("/hermes/api/organizations/{org_id}/notification/preferences")
@router.post("/hermes/organizations/{org_id}/notification/preferences")
@router.post("/api/organizations/{org_id}/notification_preferences")
@router.post("/organizations/{org_id}/notification_preferences")
@router.post("/hermes/api/organizations/{org_id}/notification_preferences")
@router.post("/hermes/organizations/{org_id}/notification_preferences")
@router.get("/api/organizations/{org_id}/notification/preferences")
@router.get("/organizations/{org_id}/notification/preferences")
@router.get("/hermes/api/organizations/{org_id}/notification/preferences")
@router.get("/hermes/organizations/{org_id}/notification/preferences")
@router.get("/api/organizations/{org_id}/notification_preferences")
@router.get("/organizations/{org_id}/notification_preferences")
@router.get("/hermes/api/organizations/{org_id}/notification_preferences")
@router.get("/hermes/organizations/{org_id}/notification_preferences")
async def register_notification_channel(request: Request, org_id: Optional[str] = None):
    token = None
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            data = await request.json()
            token = data.get("token") or data.get("device_token") or data.get("fcm_token") or data.get("registration_id")
            if token:
                _FCM_DEVICE_TOKENS.add(str(token))
                logger.info(f"Registered mobile device notification channel: {str(token)[:15]}...")
        except Exception:
            pass
    return {
        "status": "registered",
        "success": True,
        "enabled": True,
        "token": token or "registered",
        "notification_preferences": {
            "email": False,
            "push": True,
            "in_app": True
        }
    }

async def send_live_mobile_notification(title: str, body: str, chat_id: Optional[str] = None):
    """Sends a live push notification to the user's mobile device via FCM and Telegram bot."""
    # 1. Dispatch Telegram Push to registered user
    try:
        from hermes_core.telegram_bot import safe_telegram_post
        allowed_users = [u.strip() for u in os.getenv("TELEGRAM_ALLOWED_USERS", "1769298522").split(",") if u.strip()]
        for user_id in allowed_users:
            msg_text = f"🔔 *{title}*\n\n{body[:500]}"
            if len(body) > 500:
                msg_text += "..."
            asyncio.create_task(safe_telegram_post("sendMessage", {
                "chat_id": int(user_id) if user_id.isdigit() else user_id,
                "text": msg_text,
                "parse_mode": "Markdown"
            }, max_retries=1))
    except Exception as e:
        logger.debug(f"Telegram notification notice: {e}")

    # 2. Dispatch FCM Push to registered Android device tokens if FCM_SERVER_KEY is configured
    if FCM_SERVER_KEY and _FCM_DEVICE_TOKENS:
        try:
            headers = {
                "Authorization": f"key={FCM_SERVER_KEY}",
                "Content-Type": "application/json"
            }
            for token in list(_FCM_DEVICE_TOKENS):
                fcm_payload = {
                    "to": token,
                    "notification": {
                        "title": title,
                        "body": body[:200],
                        "sound": "default"
                    },
                    "data": {
                        "chat_id": chat_id or "",
                        "type": "task_completed"
                    }
                }
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post("https://fcm.googleapis.com/fcm/send", headers=headers, json=fcm_payload)
        except Exception as e:
            logger.debug(f"FCM push notice: {e}")

# 6. Chat Conversations Management
@router.get("/api/organizations/{org_id}/chat_conversations")
@router.get("/organizations/{org_id}/chat_conversations")
@router.get("/hermes/api/organizations/{org_id}/chat_conversations")
@router.get("/hermes/organizations/{org_id}/chat_conversations")
async def list_conversations(org_id: str, limit: int = 100, starred: Optional[bool] = None, consistency: Optional[str] = None):
    _load_history()
    conv_list = []
    for conv in _CONVERSATIONS.values():
        if starred and not conv.get("is_starred", False):
            continue
        conv_list.append(_build_conv_response(conv))
    conv_list.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return conv_list[:limit]

@router.post("/api/organizations/{org_id}/chat_conversations")
@router.post("/organizations/{org_id}/chat_conversations")
@router.post("/hermes/api/organizations/{org_id}/chat_conversations")
@router.post("/hermes/organizations/{org_id}/chat_conversations")
async def create_conversation(org_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    chat_id = body.get("uuid") or str(uuid.uuid4())
    name = body.get("name") or body.get("title") or "Chat"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if chat_id not in _CONVERSATIONS:
        _CONVERSATIONS[chat_id] = {
            "uuid": chat_id,
            "name": name,
            "created_at": now,
            "updated_at": now,
            "chat_messages": []
        }
        _save_history()
    return _build_conv_response(_CONVERSATIONS[chat_id])

@router.put("/api/organizations/{org_id}/chat_conversations/{chat_id}")
@router.put("/organizations/{org_id}/chat_conversations/{chat_id}")
@router.put("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}")
@router.patch("/api/organizations/{org_id}/chat_conversations/{chat_id}")
@router.patch("/organizations/{org_id}/chat_conversations/{chat_id}")
@router.patch("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}")
async def update_conversation(org_id: str, chat_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    name = body.get("name") or body.get("title") or "Chat"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if chat_id not in _CONVERSATIONS:
        _CONVERSATIONS[chat_id] = {
            "uuid": chat_id,
            "name": name,
            "created_at": now,
            "updated_at": now,
            "chat_messages": []
        }
    else:
        _CONVERSATIONS[chat_id]["name"] = name
        _CONVERSATIONS[chat_id]["updated_at"] = now
    _save_history()
    return _build_conv_response(_CONVERSATIONS[chat_id])

async def _generate_ai_title(prompt: str) -> str:
    """Generates a clean 2-4 word title using ultra-fast dedicated AI models (Gemini Flash / OpenCode) in background."""
    if not prompt or not prompt.strip():
        return "Hermes Chat"

    clean_prompt = prompt.strip()
    # 1. Try dedicated lightweight models from OmniRoute
    title_models = ["antigravity/gemini-2.5-flash", "auto/best-chat", "auto/fast"]
    from hermes_core.agent import UPSTREAM_URL, UPSTREAM_API_KEY
    headers = {
        "Authorization": f"Bearer {UPSTREAM_API_KEY}",
        "Content-Type": "application/json"
    }

    for t_model in title_models:
        try:
            payload = {
                "model": t_model,
                "messages": [
                    {"role": "system", "content": "You are a concise title generator. Generate a sharp 2 to 4 word title capturing the essence of the user prompt. Return ONLY the plain title words with NO punctuation, NO quotes, and NO model/assistant mentions."},
                    {"role": "user", "content": clean_prompt[:250]}
                ],
                "max_tokens": 12,
                "temperature": 0.2
            }
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.post(f"{UPSTREAM_URL}/chat/completions", headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    ai_title = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    ai_title = re.sub(r'[\'\"#*`\(\)\[\]:.]', '', ai_title).strip()
                    if ai_title and 2 < len(ai_title) < 50:
                        return ai_title.title()
        except Exception:
            continue

    # 2. Instant heuristic fallback
    cleaned = re.sub(r'^(?:please\s+|can\s+you\s+|how\s+to\s+|what\s+is\s+|i\s+need\s+to\s+|tell\s+me\s+about\s+|write\s+a\s+|create\s+a\s+)', '', clean_prompt, flags=re.I)
    cleaned = re.sub(r'[^\w\s-]', '', cleaned).strip()
    words = cleaned.split()
    if len(words) > 5:
        return " ".join(words[:4]).title()
    elif words:
        return " ".join(words).title()
    return "Hermes Chat"

async def _trigger_background_title_update(chat_id: str, prompt: str):
    """Background asynchronous task that calculates dynamic AI title within seconds and persists to history."""
    try:
        title = await _generate_ai_title(prompt)
        if title and title != "Hermes Chat":
            _load_history()
            if chat_id in _CONVERSATIONS:
                _CONVERSATIONS[chat_id]["name"] = title
                _CONVERSATIONS[chat_id]["summary"] = title
                _CONVERSATIONS[chat_id]["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                _save_history()
                logger.info(f"Updated dynamic title for {chat_id} -> '{title}'")
    except Exception as e:
        logger.debug(f"Background title generation error: {e}")

@router.post("/api/organizations/{org_id}/chat_conversations/{chat_id}/title")
@router.post("/organizations/{org_id}/chat_conversations/{chat_id}/title")
@router.post("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/title")
@router.post("/hermes/organizations/{org_id}/chat_conversations/{chat_id}/title")
async def set_conversation_title(org_id: str, chat_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    title = body.get("title") or body.get("name")
    
    # If client didn't supply an explicit non-generic title, generate via AI model
    if not title or title.strip() in ("Chat", "New Chat", "Hermes Chat"):
        prompt = body.get("message_content") or body.get("prompt") or ""
        if not prompt and chat_id in _CONVERSATIONS:
            msgs = _CONVERSATIONS[chat_id].get("chat_messages", [])
            if msgs:
                prompt = msgs[0].get("text", "")
        
        title = await _generate_ai_title(prompt)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if chat_id in _CONVERSATIONS:
        _CONVERSATIONS[chat_id]["name"] = title
        _CONVERSATIONS[chat_id]["summary"] = title
        _CONVERSATIONS[chat_id]["updated_at"] = now
    else:
        _CONVERSATIONS[chat_id] = {
            "uuid": chat_id,
            "name": title,
            "summary": title,
            "created_at": now,
            "updated_at": now,
            "chat_messages": []
        }
    _save_history()
    
    return {
        "title": title,
        "name": title,
        "uuid": chat_id,
        "summary": title,
        "updated_at": now
    }

@router.post("/api/organizations/{org_id}/chat_conversations/{chat_id}/stop_response")
@router.post("/organizations/{org_id}/chat_conversations/{chat_id}/stop_response")
@router.post("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/stop_response")
async def stop_conversation_response(org_id: str, chat_id: str):
    return {"status": "stopped", "uuid": chat_id}

@router.delete("/api/organizations/{org_id}/chat_conversations/{chat_id}")
@router.delete("/organizations/{org_id}/chat_conversations/{chat_id}")
@router.delete("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}")
@router.delete("/hermes/organizations/{org_id}/chat_conversations/{chat_id}")
async def delete_conversation(org_id: str, chat_id: str):
    if chat_id in _CONVERSATIONS:
        del _CONVERSATIONS[chat_id]
        _save_history()
    return {"status": "deleted", "uuid": chat_id}

@router.delete("/api/organizations/{org_id}/chat_conversations")
@router.delete("/organizations/{org_id}/chat_conversations")
@router.delete("/hermes/api/organizations/{org_id}/chat_conversations")
@router.delete("/hermes/organizations/{org_id}/chat_conversations")
@router.post("/api/admin/clear_conversations")
@router.post("/hermes/api/admin/clear_conversations")
@router.get("/api/admin/clear_conversations")
@router.get("/hermes/api/admin/clear_conversations")
async def clear_all_conversations(org_id: Optional[str] = None):
    """Completely purges and resets all stored conversation history on disk."""
    global _CONVERSATIONS
    _CONVERSATIONS.clear()
    _save_history()
    logger.info("Cleared all conversation history across storage.")
    return {"status": "cleared", "total_remaining": 0, "message": "All chat history has been permanently wiped."}

@router.get("/api/organizations/{org_id}/chat_conversations/{chat_id}")
@router.get("/organizations/{org_id}/chat_conversations/{chat_id}")
@router.get("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}")
@router.get("/hermes/organizations/{org_id}/chat_conversations/{chat_id}")
async def get_conversation(org_id: str, chat_id: str):
    _load_history()
    if chat_id not in _CONVERSATIONS:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _CONVERSATIONS[chat_id] = {
            "uuid": chat_id,
            "name": "Chat",
            "summary": "Chat",
            "created_at": now,
            "updated_at": now,
            "chat_messages": []
        }
        _save_history()
    return _build_conv_response(_CONVERSATIONS[chat_id])

# Background execution tracking
_ACTIVE_RUNS = {}

async def _execute_agent_background(chat_id: str, prompt: str, messages: list, model: str, msg_id: str, queue: asyncio.Queue):
    """Autonomous agent runner that executes to completion in the background without UI thinking drawers."""
    full_text = ""
    text_active = False
    
    try:
        await queue.put(ab.create_message_start(msg_id, model))

        async for chunk in agent.stream_chat(messages, model=model):
            ctype = chunk.get("type")
            # Filter out thinking blocks so chat stays clean and direct
            if ctype == "thinking":
                continue
            elif ctype == "text":
                delta = chunk.get("content", "")
                if delta:
                    if not text_active:
                        await queue.put(ab.create_content_block_start(0))
                        text_active = True
                    full_text += delta
                    await queue.put(ab.create_content_block_delta(delta, 0))
            elif ctype == "error":
                err = chunk.get("error", "")
                err_msg = f"\n\n[Error: {err}]"
                if not text_active:
                    await queue.put(ab.create_content_block_start(0))
                    text_active = True
                full_text += err_msg
                await queue.put(ab.create_content_block_delta(err_msg, 0))

        if text_active:
            await queue.put(ab.create_content_block_stop(0))
        else:
            await queue.put(ab.create_content_block_start(0))
            await queue.put(ab.create_content_block_delta("", 0))
            await queue.put(ab.create_content_block_stop(0))

        await queue.put(ab.create_message_delta("end_turn"))
        await queue.put(ab.create_message_stop())
    except Exception as e:
        logger.error(f"Error in background agent execution for {chat_id}: {e}")
        try:
            await queue.put(ab.create_message_delta("end_turn"))
            await queue.put(ab.create_message_stop())
        except Exception:
            pass
    finally:
        # Guarantee conversation history is saved to disk
        try:
            if chat_id not in _CONVERSATIONS:
                now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                _CONVERSATIONS[chat_id] = {
                    "uuid": chat_id,
                    "name": "Chat",
                    "summary": "Chat",
                    "created_at": now,
                    "updated_at": now,
                    "chat_messages": []
                }
            
            # If title is still default, generate AI title asynchronously
            curr_title = _CONVERSATIONS[chat_id].get("name", "Chat")
            if curr_title in ("Chat", "New Chat", "Hermes Chat") and prompt:
                ai_title = await _generate_ai_title(prompt)
                _CONVERSATIONS[chat_id]["name"] = ai_title
                _CONVERSATIONS[chat_id]["summary"] = ai_title

            msgs = _CONVERSATIONS[chat_id]["chat_messages"]
            prev_uuid = msgs[-1]["uuid"] if msgs else None
            
            asst_msg = _format_msg("assistant", full_text, len(msgs), prev_uuid, msg_id=msg_id)
            asst_msg["content"] = [
                {"type": "text", "text": full_text}
            ]
            msgs.append(asst_msg)
            _CONVERSATIONS[chat_id]["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _save_history()

            # Trigger live push notification to user's mobile device
            title_text = _CONVERSATIONS[chat_id].get("name") or "Hermes Task Complete"
            preview_snippet = full_text[:280].strip() if full_text else "Task completed successfully."
            asyncio.create_task(send_live_mobile_notification(f"Hermes Agent: {title_text}", preview_snippet, chat_id=chat_id))
        except Exception as se:
            logger.error(f"Failed to save conversation history for {chat_id}: {se}")
        
        # Signal queue completion immediately
        await queue.put(None)
        if chat_id in _ACTIVE_RUNS:
            del _ACTIVE_RUNS[chat_id]


# 7. Conversation Completion (Streaming Claude Web / App Protocol with Thinking Support)
@router.post("/api/organizations/{org_id}/chat_conversations/{chat_id}/completion")
@router.post("/organizations/{org_id}/chat_conversations/{chat_id}/completion")
@router.post("/api/organizations/{org_id}/chat_conversations/{chat_id}/retry_completion")
@router.post("/organizations/{org_id}/chat_conversations/{chat_id}/retry_completion")
@router.post("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/completion")
@router.post("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/retry_completion")
async def conversation_completion(org_id: str, chat_id: str, request: Request):
    body = await request.json()
    prompt = body.get("prompt", "")
    attachments = body.get("attachments", [])
    files = body.get("files", [])
    model = "hermes-agent"
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    file_context_blocks = []
    for att in attachments:
        fname = att.get("file_name", "file")
        fcontent = att.get("extracted_content") or att.get("content", "")
        if fcontent:
            file_context_blocks.append(f"[Attached File: {fname}]\n{fcontent}")
    for f in files:
        fname = f.get("file_name", "file")
        fcontent = f.get("extracted_content") or f.get("content", "")
        if fcontent:
            file_context_blocks.append(f"[Attached File: {fname}]\n{fcontent}")

    full_prompt = prompt
    if file_context_blocks:
        full_prompt += "\n\n" + "\n\n".join(file_context_blocks)

    # Save user message immediately
    if chat_id not in _CONVERSATIONS:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _CONVERSATIONS[chat_id] = {
            "uuid": chat_id,
            "name": prompt[:30] if prompt else "Chat",
            "created_at": now,
            "updated_at": now,
            "chat_messages": []
        }
    
    msgs = _CONVERSATIONS[chat_id]["chat_messages"]
    prev_uuid = msgs[-1]["uuid"] if msgs else None
    user_msg = _format_msg("human", prompt, len(msgs), prev_uuid)
    if attachments:
        user_msg["attachments"] = attachments
    if files:
        user_msg["files"] = files
    msgs.append(user_msg)
    _save_history()

    # Trigger background AI title worker immediately upon chat start (first message)
    if len(msgs) <= 1 and prompt:
        asyncio.create_task(_trigger_background_title_update(chat_id, prompt))

    history = _CONVERSATIONS[chat_id].get("chat_messages", [])
    formatted = []
    for h in history:
        role = "user" if h.get("sender") == "human" else "assistant"
        msg_text = h.get("text", "")
        content_blocks = h.get("content", [])
        if content_blocks and isinstance(content_blocks, list):
            for cb in content_blocks:
                if isinstance(cb, dict) and cb.get("type") == "text":
                    msg_text = cb.get("text", "")
        if msg_text:
            formatted.append({"role": role, "content": msg_text})
    
    messages = formatted if formatted else [{"role": "user", "content": full_prompt}]
    if messages and messages[-1].get("role") == "user":
        messages[-1]["content"] = full_prompt

    # Create stream queue & launch decoupled background runner
    queue = asyncio.Queue()
    bg_task = asyncio.create_task(_execute_agent_background(chat_id, full_prompt, messages, model, msg_id, queue))
    _ACTIVE_RUNS[chat_id] = {"task": bg_task, "queue": queue}

    async def event_stream():
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=15.0)
                if item is None:
                    break
                yield item
            except asyncio.TimeoutError:
                # Emit SSE keep-alive heartbeat comment to prevent mobile proxy timeouts
                yield ": keep-alive\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )

# 8. Artifacts & In-Chat Files Endpoints
_UPLOADED_FILES: Dict[str, Dict[str, Any]] = {}

def _extract_artifacts_from_conv(chat_id: str) -> List[Dict[str, Any]]:
    conv = _CONVERSATIONS.get(chat_id, {})
    artifacts = []
    seen_ids = set()
    for msg in conv.get("chat_messages", []):
        text = msg.get("text", "")
        for match in re.finditer(r'<antArtifact\s+([^>]+)>([\s\S]*?)</antArtifact>', text):
            attrs_str = match.group(1)
            content = match.group(2).strip()
            attrs = dict(re.findall(r'([a-zA-Z0-9_]+)="([^"]+)"', attrs_str))
            art_id = attrs.get("identifier") or attrs.get("id") or str(uuid.uuid4())
            if art_id not in seen_ids:
                seen_ids.add(art_id)
                artifacts.append({
                    "id": art_id,
                    "uuid": art_id,
                    "version_uuid": str(uuid.uuid4()),
                    "identifier": art_id,
                    "type": attrs.get("type", "application/vnd.ant.markdown"),
                    "title": attrs.get("title", "Document"),
                    "language": attrs.get("language", ""),
                    "content": content,
                    "is_complete": True,
                    "created_at": msg.get("created_at"),
                    "updated_at": msg.get("updated_at")
                })
    return artifacts

@router.get("/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts")
@router.get("/organizations/{org_id}/chat_conversations/{chat_id}/artifacts")
@router.get("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts")
async def list_conversation_artifacts(org_id: str, chat_id: str):
    artifacts = _extract_artifacts_from_conv(chat_id)
    return {"artifacts": artifacts, "data": artifacts}

@router.get("/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}")
@router.get("/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}")
@router.get("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}")
async def get_artifact(org_id: str, chat_id: str, artifact_id: str):
    artifacts = _extract_artifacts_from_conv(chat_id)
    for art in artifacts:
        if art.get("id") == artifact_id or art.get("identifier") == artifact_id:
            return art
    return {"id": artifact_id, "identifier": artifact_id, "type": "application/vnd.ant.markdown", "title": "Document", "content": "", "is_complete": True}

@router.get("/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/versions")
@router.get("/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/versions")
async def get_artifact_versions(org_id: str, chat_id: str, artifact_id: str):
    artifacts = _extract_artifacts_from_conv(chat_id)
    for art in artifacts:
        if art.get("id") == artifact_id or art.get("identifier") == artifact_id:
            return {"versions": [art], "data": [art]}
    return {"versions": [], "data": []}

@router.post("/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/publish")
@router.post("/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/publish")
async def publish_artifact(org_id: str, chat_id: str, artifact_id: str, request: Request):
    return {"status": "published", "artifact_id": artifact_id, "url": f"https://claude.ai/artifacts/{artifact_id}"}

@router.post("/api/organizations/{org_id}/chat_conversations/{chat_id}/files")
@router.post("/organizations/{org_id}/chat_conversations/{chat_id}/files")
@router.post("/api/organizations/{org_id}/files")
@router.post("/organizations/{org_id}/files")
@router.post("/api/files")
async def upload_file(request: Request):
    try:
        body = await request.json()
        file_name = body.get("file_name", "uploaded_file.txt")
        file_content = body.get("content") or body.get("extracted_content") or ""
        file_type = body.get("file_type", "text/plain")
        file_size = len(file_content.encode("utf-8")) if file_content else body.get("file_size", 0)
    except Exception:
        file_name = "file.txt"
        file_content = ""
        file_type = "text/plain"
        file_size = 0
    
    file_id = f"file_{uuid.uuid4().hex[:16]}"
    file_record = {
        "id": file_id,
        "file_name": file_name,
        "file_size": file_size,
        "file_type": file_type,
        "extracted_content": file_content
    }
    _UPLOADED_FILES[file_id] = file_record
    return file_record

@router.get("/api/organizations/{org_id}/chat_conversations/{chat_id}/files/{file_id}")
@router.get("/organizations/{org_id}/chat_conversations/{chat_id}/files/{file_id}")
@router.get("/api/organizations/{org_id}/files/{file_id}")
@router.get("/organizations/{org_id}/files/{file_id}")
@router.get("/api/files/{file_id}")
async def get_file(file_id: str):
    if file_id in _UPLOADED_FILES:
        return _UPLOADED_FILES[file_id]
    return {"id": file_id, "file_name": "file.txt", "file_size": 0, "file_type": "text/plain", "extracted_content": ""}

# 9. Directory & Feature Flags
@router.get("/v1/directory/servers")
# 9. Projects & Feature Flags
@router.get("/api/organizations/{org_id}/projects_v2")
@router.get("/organizations/{org_id}/projects_v2")
@router.get("/hermes/api/organizations/{org_id}/projects_v2")
@router.get("/hermes/organizations/{org_id}/projects_v2")
async def get_projects_v2(org_id: str, limit: int = 30, starred: Optional[bool] = None, is_archived: bool = False):
    return {"projects": [], "data": [], "has_more": False}

@router.get("/v1/directory/servers")
@router.get("/directory/servers")
@router.get("/api/v1/directory/servers")
@router.get("/api/directory/servers")
@router.get("/hermes/v1/directory/servers")
async def directory_servers():
    return {
        "servers": [],
        "data": [],
        "has_more": False
    }

@router.get("/api/organizations/{org_id}/feature_flags")
@router.get("/organizations/{org_id}/feature_flags")
@router.get("/hermes/api/organizations/{org_id}/feature_flags")
async def feature_flags(org_id: str):
    return {
        "flags": {
            "claude_3_5_sonnet": True,
            "claude_3_opus": True,
            "artifacts": False,
            "memory": True,
            "latex": True,
            "model_selector_enabled": True,
            "voice": True,
            "speech_input": True,
            "read_aloud": True,
            "tts": True
        }
    }

# 10. Speech & Audio Synthesis Endpoints (TTS / Read-Aloud / Voice)
# Sarvam AI Bulbul:v3 (Primary when SARVAM_API_KEY is set) + 100% Free Edge-TTS Fallback
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "").strip()
DEFAULT_SARVAM_SPEAKER = os.getenv("SARVAM_SPEAKER", "ritu")
DEFAULT_SARVAM_LANG = os.getenv("SARVAM_LANG", "en-IN")

# 100% Free Verified Edge-TTS Fallback Neural Voice Models
DEFAULT_FEMALE_VOICE = "en-US-AvaNeural"  # Young Adult Female (20-22 yrs, warm, expressive)

VOICE_MAP = {
    "buttery": "en-US-AvaNeural",      # Young Adult Female, warm & conversational
    "ritu": "en-IN-NeerjaNeural",      # Indian English young female fallback
    "sara": "en-US-AvaNeural",
    "bree": "en-US-EmmaNeural",
    "natural": "en-US-AvaNeural",
    "jenny": "en-US-JennyNeural",
    "classic": "en-US-JennyNeural",
    "aria": "en-US-AriaNeural",
    "voice_1": "en-US-AvaNeural",
    "voice_2": "en-US-JennyNeural"
}

async def fetch_sarvam_tts_audio(text: str, speaker: str = DEFAULT_SARVAM_SPEAKER, lang: str = DEFAULT_SARVAM_LANG) -> Optional[bytes]:
    """Synthesizes speech using Sarvam AI bulbul:v3 (speaker: ritu)."""
    # Fetch dynamically from env in case added via HF Space Secrets without rebuild
    key = os.getenv("SARVAM_API_KEY", "").strip() or SARVAM_API_KEY
    if not key:
        return None
    try:
        url = "https://api.sarvam.ai/text-to-speech"
        headers = {
            "api-subscription-key": key,
            "Content-Type": "application/json"
        }
        payload = {
            "text": text[:2500],
            "language_code": lang,
            "speaker": speaker,
            "model": "bulbul:v3",
            "pace": 1.0,
            "speech_sample_rate": 22050
        }
        logger.info(f"Invoking Sarvam AI bulbul:v3 (speaker={speaker}, lang={lang}, len={len(text)})...")
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                audios = data.get("audios", [])
                if audios:
                    import base64
                    logger.info(f"Sarvam AI bulbul:v3 returned audio payload ({len(audios[0])} base64 chars)")
                    return base64.b64decode(audios[0])
            else:
                logger.warning(f"Sarvam AI TTS returned HTTP {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.warning(f"Sarvam AI TTS attempt note: {e}")
    return None

@router.websocket("/ws/text_to_speech/text_stream")
@router.websocket("/api/ws/text_to_speech/text_stream")
@router.websocket("/hermes/ws/text_to_speech/text_stream")
@router.websocket("/hermes/api/ws/text_to_speech/text_stream")
async def tts_websocket_stream(websocket: WebSocket):
    await websocket.accept()
    query_params = websocket.query_params
    voice_param = query_params.get("voice", "buttery")
    out_format = query_params.get("output_format", "pcm_16000")
    tts_voice = VOICE_MAP.get(voice_param, DEFAULT_FEMALE_VOICE)
    
    logger.info(f"TTS WebSocket connected (voice={tts_voice}, sarvam_enabled={bool(SARVAM_API_KEY)}, format={out_format})")

    async def _generate_edge_audio_chunks(text_input: str, voice_name: str):
        import edge_tts
        communicate = edge_tts.Communicate(text_input, voice_name)
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return chunks

    async def _stream_pcm_audio(text: str):
        """Synthesizes via Sarvam AI (bulbul:v3 ritu) and falls back to Edge-TTS seamlessly."""
        raw_audio_bytes = None
        sarvam_key = os.getenv("SARVAM_API_KEY", "").strip() or os.getenv("SARVAMAI_API_KEY", "").strip() or SARVAM_API_KEY

        # 1. Try Sarvam AI bulbul:v3 (Ritu / en-IN)
        if sarvam_key:
            raw_audio_bytes = await fetch_sarvam_tts_audio(text)
        else:
            logger.info("SARVAM_API_KEY not found in environment; using high-fidelity EdgeTTS neural engine")

        # 2. Fallback to 100% Free Edge-TTS if Sarvam AI is not configured or fails
        if not raw_audio_bytes:
            for voice_candidate in [tts_voice, "en-US-AvaNeural", "en-IN-NeerjaNeural", "en-US-JennyNeural"]:
                try:
                    chunks = await _generate_edge_audio_chunks(text, voice_candidate)
                    if chunks:
                        raw_audio_bytes = b"".join(chunks)
                        break
                except Exception as e:
                    logger.warning(f"EdgeTTS fallback candidate {voice_candidate} notice: {e}")

        if not raw_audio_bytes:
            logger.error("All TTS engines (Sarvam AI & EdgeTTS) failed to synthesize audio")
            return

        if "pcm" in out_format:
            # Transcode input audio buffer to raw 16-bit 16kHz mono PCM via ffmpeg
            try:
                ffmpeg_proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-loglevel", "quiet",
                    "-i", "pipe:0",
                    "-f", "s16le",
                    "-acodec", "pcm_s16le",
                    "-ac", "1",
                    "-ar", "16000",
                    "pipe:1",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL
                )
                stdout_data, _ = await ffmpeg_proc.communicate(input=raw_audio_bytes)
                if stdout_data:
                    for offset in range(0, len(stdout_data), 4096):
                        chunk = stdout_data[offset:offset+4096]
                        await websocket.send_bytes(chunk)
            except Exception as e:
                logger.error(f"FFmpeg PCM conversion failed: {e}")
        else:
            await websocket.send_bytes(raw_audio_bytes)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except Exception:
                continue
                
            msg_type = msg.get("type", "")
            if msg_type == "keep_alive":
                continue
            elif msg_type in ("text", "text_chunk", "TextChunkInputMessage"):
                text_content = msg.get("text", "")
                if text_content and text_content.strip():
                    # Clean out markdown and asterisks before speaking
                    cleaned_text = re.sub(r'[*_#`~>\[\]()|]', '', text_content)
                    cleaned_text = re.sub(r'<antArtifact[\s\S]*?</antArtifact>', '', cleaned_text).strip()
                    if cleaned_text:
                        try:
                            await _stream_pcm_audio(cleaned_text)
                        except Exception as e:
                            logger.error(f"TTS Stream error: {e}")
    except WebSocketDisconnect:
        logger.info("TTS WebSocket client disconnected")
    except Exception as e:
        logger.warning(f"TTS WebSocket loop ended: {e}")

@router.post("/api/organizations/{org_id}/tts")
@router.post("/organizations/{org_id}/tts")
@router.post("/api/tts")
@router.post("/v1/audio/speech")
@router.post("/audio/speech")
@router.post("/hermes/api/organizations/{org_id}/tts")
@router.post("/hermes/v1/audio/speech")
async def synthesize_speech(request: Request, org_id: Optional[str] = None):
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    text = body.get("text") or body.get("input") or ""
    voice_name = body.get("voice", "buttery")
    tts_voice = VOICE_MAP.get(voice_name, DEFAULT_FEMALE_VOICE)
    
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, tts_voice)
        async def audio_generator():
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
        return StreamingResponse(audio_generator(), media_type="audio/mpeg")
    except Exception as e:
        logger.warning(f"Fallback to silence frame: {e}")
        silence_mp3 = b"\xff\xfb\x90d\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        return StreamingResponse(iter([silence_mp3]), media_type="audio/mpeg")

@router.post("/api/organizations/{org_id}/speech_to_text")
@router.post("/organizations/{org_id}/speech_to_text")
@router.post("/v1/audio/transcriptions")
@router.post("/audio/transcriptions")
@router.post("/hermes/api/organizations/{org_id}/speech_to_text")
async def speech_to_text(request: Request, org_id: Optional[str] = None):
    return {"text": "", "language": "en"}

# 11. Telegram Webhook & Status Endpoints
@router.post("/api/webhooks/telegram")
@router.post("/webhooks/telegram")
@router.post("/hermes/api/webhooks/telegram")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        msg = data.get("message") or data.get("edited_message") or {}
        chat_id = msg.get("chat", {}).get("id")
        user_id = str(msg.get("from", {}).get("id", ""))
        text = msg.get("text", "")

        from hermes_core.telegram_bot import process_telegram_update, generate_hermes_telegram_reply
        
        # In Telegram webhook protocol, returning {"method": "sendMessage", "chat_id": ..., "text": ...} in the HTTP 200 response body delivers the message instantly without making outbound HTTP calls!
        if chat_id and text:
            # Also dispatch async processor
            asyncio.create_task(process_telegram_update(data))
            reply_text = await generate_hermes_telegram_reply(text, user_id, chat_id)
            return {
                "method": "sendMessage",
                "chat_id": chat_id,
                "text": reply_text[:4000]
            }
    except Exception as e:
        logger.warning(f"Webhook update error: {e}")
    return {"ok": True, "status": "received"}

@router.get("/gradio_api/info")
@router.get("/hermes/gradio_api/info")
async def gradio_info():
    return {"named_endpoints": {}, "unnamed_endpoints": {}}



