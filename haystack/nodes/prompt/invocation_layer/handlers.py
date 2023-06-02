from abc import abstractmethod, ABC
from typing import Union, Dict

from transformers import PreTrainedTokenizer, PreTrainedTokenizerFast, TextStreamer, AutoTokenizer


class TokenStreamingHandler(ABC):
    """
    TokenStreamingHandler implementations handle the streaming of tokens from the stream.
    """

    DONE_MARKER = "[DONE]"

    @abstractmethod
    def __call__(self, token_received: str, **kwargs) -> str:
        """
        This callback method is called when a new token is received from the stream.

        :param token_received: The token received from the stream.
        :param kwargs: Additional keyword arguments passed to the handler.
        :return: The token to be sent to the stream.
        """
        pass


class DefaultTokenStreamingHandler(TokenStreamingHandler):
    def __call__(self, token_received, **kwargs) -> str:
        """
        This callback method is called when a new token is received from the stream.

        :param token_received: The token received from the stream.
        :param kwargs: Additional keyword arguments passed to the handler.
        :return: The token to be sent to the stream.
        """
        print(token_received, flush=True, end="")
        return token_received


class AnthropicTokenStreamingHandler(TokenStreamingHandler):
    """
    Anthropic has an unusual way of handling streaming responses
    as it returns all the tokens generated up to that point for each
    response.
    This makes it hard to use DefaultTokenStreamingHandler as the user
    would see the generated text printed multiple times.

    This streaming handler tackles the repeating text and prints
    only the newly generated part.
    """

    def __init__(self, token_handler: TokenStreamingHandler):
        self.token_handler = token_handler
        self.previous_text = ""

    def __call__(self, token_received: str, **kwargs) -> str:
        """
        When the handler is called directly with a response string from Anthropic,
        we split it, comparing it with the previously received text by this handler,
        and return only the new part.

        If the text is completely different from the previously received one, we
        replace it and return it in full.

        :param token_received: Text response received by Anthropic backend.
        :type token_received: str
        :return: The part of text that has not been received previously.
        :rtype: str
        """
        if self.previous_text not in token_received:
            # The handler is being reused, we want to handle this case gracefully
            # so we just cleanup the previously received text and keep going
            self.previous_text = ""

        previous_text_length = len(self.previous_text)
        chopped_text = token_received[previous_text_length:]
        self.token_handler(chopped_text)
        self.previous_text = token_received
        return chopped_text


class HFTokenStreamingHandler(TextStreamer):
    def __init__(
        self, tokenizer: Union[PreTrainedTokenizer, PreTrainedTokenizerFast], stream_handler: TokenStreamingHandler
    ):
        super().__init__(tokenizer=tokenizer)
        self.token_handler = stream_handler

    def on_finalized_text(self, token: str, stream_end: bool = False):
        token_to_send = token + "\n" if stream_end else token
        self.token_handler(token_received=token_to_send, **{})


class DefaultPromptHandler:
    """
    DefaultPromptHandler resizes the prompt to ensure that the prompt and answer token lengths together
    are within the model_max_length.
    """

    def __init__(self, model_name_or_path: str, model_max_length: int, max_length: int = 100):
        self.tokenizer = AutoTokenizer.from_pretrained(model_name_or_path)
        self.model_max_length = model_max_length
        self.max_length = max_length

    def __call__(self, prompt: str, **kwargs) -> Dict[str, Union[str, int]]:
        """
        Resizes the prompt to ensure that the prompt and answer is within the model_max_length

        :param prompt: the prompt to be sent to the model.
        :param kwargs: Additional keyword arguments passed to the handler.
        :return: A dictionary containing the resized prompt and additional information.
        """
        resized_prompt = prompt
        prompt_length = 0
        new_prompt_length = 0

        if prompt:
            prompt_length = len(self.tokenizer.tokenize(prompt))
            if (prompt_length + self.max_length) <= self.model_max_length:
                resized_prompt = prompt
                new_prompt_length = prompt_length
            else:
                tokenized_payload = self.tokenizer.tokenize(prompt)
                resized_prompt = self.tokenizer.convert_tokens_to_string(
                    tokenized_payload[: self.model_max_length - self.max_length]
                )
                new_prompt_length = len(tokenized_payload[: self.model_max_length - self.max_length])

        return {
            "resized_prompt": resized_prompt,
            "prompt_length": prompt_length,
            "new_prompt_length": new_prompt_length,
            "model_max_length": self.model_max_length,
            "max_length": self.max_length,
        }
