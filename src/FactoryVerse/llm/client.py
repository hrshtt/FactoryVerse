import logging
from typing import List, Dict, Any, Optional
from openai import OpenAI

logger = logging.getLogger(__name__)

class PrimeIntellectClient:
    """
    Wrapper for the Prime Intellect Inference API (OpenAI-compatible).
    """

    def __init__(self, 
                 api_key: str, 
                 base_url: str = "https://api.pinference.ai/api/v1",
                 model: str = "prime-intellect/intellect-3",
                 default_headers: Optional[Dict[str, str]] = None):
        
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=default_headers
        )
        self.model = model
        logger.info(f"Initialized PrimeIntellectClient with model: {model}")

    def chat_completion(self, 
                        messages: List[Dict[str, Any]], 
                        tools: Optional[List[Dict[str, Any]]] = None) -> Any:
        """
        Send a chat completion request to the LLM.
        """
        try:
            # Prepare arguments
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.1, # Low temperature for agentic actions
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            # Execute request
            response = self.client.chat.completions.create(**kwargs)
            return response.choices[0].message
            
        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            raise
