import json
import uuid

def create_message_start(message_id: str, model: str, input_tokens: int = 10) -> str:
    event = {
        "type": "message_start",
        "message": {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": 0
            }
        }
    }
    return f"event: message_start\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"

def create_thinking_block_start(index: int = 0) -> str:
    event = {
        "type": "content_block_start",
        "index": index,
        "content_block": {
            "type": "thinking",
            "thinking": ""
        }
    }
    return f"event: content_block_start\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"

def create_thinking_block_delta(thinking: str, index: int = 0) -> str:
    event = {
        "type": "content_block_delta",
        "index": index,
        "delta": {
            "type": "thinking_delta",
            "thinking": thinking
        }
    }
    return f"event: content_block_delta\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"

def create_thinking_block_stop(index: int = 0) -> str:
    event = {
        "type": "content_block_stop",
        "index": index
    }
    return f"event: content_block_stop\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"

def create_content_block_retract(from_index: int = 0) -> str:
    event = {
        "type": "content_block_retract",
        "from_index": from_index
    }
    return f"event: content_block_retract\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"

def create_thinking_summary_start(summary: str = "", index: int = 0) -> str:
    event = {
        "type": "content_block_start",
        "index": index,
        "content_block": {
            "type": "thinking_summary",
            "summary": summary
        }
    }
    return f"event: content_block_start\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"

def create_thinking_summary_delta(summary: str, index: int = 0) -> str:
    event = {
        "type": "content_block_delta",
        "index": index,
        "delta": {
            "type": "thinking_summary_delta",
            "summary": summary
        }
    }
    return f"event: content_block_delta\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"

def create_content_block_start(index: int = 0) -> str:
    event = {
        "type": "content_block_start",
        "index": index,
        "content_block": {
            "type": "text",
            "text": ""
        }
    }
    return f"event: content_block_start\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"

def create_content_block_delta(text: str, index: int = 0) -> str:
    event = {
        "type": "content_block_delta",
        "index": index,
        "delta": {
            "type": "text_delta",
            "text": text
        }
    }
    return f"event: content_block_delta\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"

def create_content_block_stop(index: int = 0) -> str:
    event = {
        "type": "content_block_stop",
        "index": index
    }
    return f"event: content_block_stop\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"

def create_message_delta(stop_reason: str = "end_turn", output_tokens: int = 15) -> str:
    event = {
        "type": "message_delta",
        "delta": {
            "stop_reason": stop_reason,
            "stop_sequence": None
        },
        "usage": {
            "output_tokens": output_tokens
        }
    }
    return f"event: message_delta\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"

def create_message_stop() -> str:
    event = {
        "type": "message_stop"
    }
    return f"event: message_stop\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"
