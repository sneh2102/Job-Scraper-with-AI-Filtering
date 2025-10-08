import requests
import time

class OllamaAssistant:
    def __init__(self, model="gemma3:4b"):
        self.model = model

    def submit_message(self, prompt):
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False}
        )
        if response.status_code == 200:
            print("Ollama API response received.")
            print("Response:", response.json())
            return response.json()["response"].strip()
        else:
            raise Exception(f"Ollama API Error: {response.text}")
