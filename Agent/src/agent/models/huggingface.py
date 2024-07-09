from typing import Callable

import jellyfish
from transformers import AutoModelForCausalLM
from transformers import AutoTokenizer

from agent.models.llm import LanguageBackend


class HuggingFaceLanguageBackend(LanguageBackend):
    def __init__(
        self,
        model_id,
        logger,
        context_length,
        model_kwargs,
        tokenizer_kwargs,
        **kwargs,
    ):
        super().__init__(model_id, logger, context_length)
        self.model = AutoModelForCausalLM.from_pretrained(model_id, **model_kwargs)
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, **tokenizer_kwargs)
        self.generation_kwargs = kwargs

    def count_tokens(self, messages: list[dict[str, str]]) -> int:
        """Counts the number of tokens in a given text according to the model's tokenizer.

        Args:
            messages (list[dict[str, str]]): The list of messages to count tokens for.

        Returns:
            int: The number of tokens after encoding the prompt.
        """
        #
        prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        tokens = self.tokenizer.encode(prompt)
        return len(tokens)

    def _chat_completion(self, messages: list[dict[str, str]], parse_func: Callable, **kwargs) -> str:
        """Generates a text completion for a given prompt in a chat-like interaction.

        Args:
            messages (list[dict[str, str]]): The input text prompt to generate completion for.
            parse_func (Callable): A function to parse the model's response.
            **kwargs: Additional keyword arguments that may be required for the generation,
                      such as temperature, max_tokens, etc.

        Returns:
            str: The generated text completion.
        """
        prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer(prompt, return_tensors="pt").input_ids.to(self.model.device)
        outputs = self.model.generate(inputs, **self.generation_kwargs)

        reply = self.tokenizer.batch_decode(outputs[:, inputs.shape[1] :], skip_special_tokens=True)[0].strip()
        parsed_response = parse_func(reply)
        self.history.append({"input": messages, "output": reply, "parsed_response": parsed_response})
        self.logger.log_metrics(
            {
                "llm:input": messages,
                "llm:output": reply,
                "llm:parsed_response": parsed_response,
            }
        )

        return parsed_response
