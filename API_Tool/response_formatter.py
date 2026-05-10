import json

class ResponseFormatter:
    @staticmethod
    def format_ui_response(gui, body_text):
        """Returns a pretty-printed JSON string if possible, else returns original."""
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
            
        except Exception as e:
            # If you want to see why it's failing, uncomment the line below:
            # print(f"JSON Formatting Error: {e}")
            
            # Fallback: Return original data as a safe string
            if isinstance(body_text, bytes):
                return body_text.decode("utf-8", errors="replace")
            return str(body_text)