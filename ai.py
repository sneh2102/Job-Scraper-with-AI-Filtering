# ai.py
import os
from ollama import Client

class OllamaAssistant:
    def __init__(self, model="gemma4:31b-cloud"):
        self.model = model
        api_key = os.environ.get("OLLAMA_API_KEY", "81fba5b4157b416681be0922f413dcb3.OyX9vz7_ERoW9yUdd27FfBUr")

        # Use cloud host if model ends with -cloud or API key is set
        if api_key or model.endswith("-cloud"):
            self.client = Client(
                host="https://ollama.com",
                headers={"Authorization": f"Bearer {api_key}"}
            )
        else:
            self.client = Client(host="http://localhost:11434")

    def submit_message(self, prompt):
        response = self.client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            options={
                "num_predict": 16384,      # ← unlimited
                "num_ctx":     32768,   # ← large context
                "temperature": 0.3,
            },
        )
        return response["message"]["content"].strip()