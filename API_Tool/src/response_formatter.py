import json

class ResponseFormatter:
    @staticmethod
    def format_ui_response(gui, body_text):
        """Returns a pretty-printed JSON string if possible, else best-effort formatted."""
        if not body_text: 
            return ""
            
        try:
            # 1. Force conversion to string if it's bytes
            if isinstance(body_text, (bytes, bytearray)):
                data = body_text.decode("utf-8", errors="replace")
            else:
                data = str(body_text)
            
            # 2. Strip any leading/trailing whitespace that might trip up the parser
            data = data.strip()
            
            # 3. Attempt to parse
            parsed = json.loads(data)
            
            # 4. Return the prettified version
            return json.dumps(parsed, indent=4, ensure_ascii=False)
            
        except Exception:
            # Fallback: best-effort format even if malformed
            if isinstance(body_text, bytes):
                data = body_text.decode("utf-8", errors="replace")
            else:
                data = str(body_text)
            try:
                from text_helpers import best_effort_pretty_print
                return best_effort_pretty_print(data.strip())
            except Exception:
                return data