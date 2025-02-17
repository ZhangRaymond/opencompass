import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Union

import requests

from opencompass.utils.prompt import PromptList

from .base_api import BaseAPIModel

PromptType = Union[PromptList, str]


class MiniMax(BaseAPIModel):
    """Model wrapper around MiniMax.

    Documentation: https://api.minimax.chat/document/guides/chat-pro

    Args:
        path (str): The name of MiniMax model.
            e.g. `abab5.5-chat`
        model_type (str): The type of the model
            e.g. `chat`
        group_id (str): The id of group(like the org ID of group)
        key (str): Authorization key.
        query_per_second (int): The maximum queries allowed per second
            between two consecutive calls of the API. Defaults to 1.
        max_seq_len (int): Unused here.
        meta_template (Dict, optional): The model's meta prompt
            template if needed, in case the requirement of injecting or
            wrapping of any meta instructions.
        retry (int): Number of retires if the API call fails. Defaults to 2.
    """

    def __init__(
        self,
        path: str,
        key: str,
        group_id: str,
        model_type: str = 'chat',
        url:
        str = 'https://api.minimax.chat/v1/text/chatcompletion_pro?GroupId=',
        query_per_second: int = 2,
        max_seq_len: int = 2048,
        meta_template: Optional[Dict] = None,
        retry: int = 2,
    ):
        super().__init__(path=path,
                         max_seq_len=max_seq_len,
                         query_per_second=query_per_second,
                         meta_template=meta_template,
                         retry=retry)
        self.headers = {
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json',
        }
        self.type = model_type
        self.url = url + group_id
        self.model = path

    def generate(
        self,
        inputs: List[str or PromptList],
        max_out_len: int = 512,
    ) -> List[str]:
        """Generate results given a list of inputs.

        Args:
            inputs (List[str or PromptList]): A list of strings or PromptDicts.
                The PromptDict should be organized in OpenCompass'
                API format.
            max_out_len (int): The maximum length of the output.

        Returns:
            List[str]: A list of generated strings.
        """
        with ThreadPoolExecutor() as executor:
            results = list(
                executor.map(self._generate, inputs,
                             [max_out_len] * len(inputs)))
        self.flush()
        return results

    def flush(self):
        """Flush stdout and stderr when concurrent resources exists.

        When use multiproessing with standard io rediected to files, need to
        flush internal information for examination or log loss when system
        breaks.
        """
        if hasattr(self, 'tokens'):
            sys.stdout.flush()
            sys.stderr.flush()

    def acquire(self):
        """Acquire concurrent resources if exists.

        This behavior will fall back to wait with query_per_second if there are
        no concurrent resources.
        """
        if hasattr(self, 'tokens'):
            self.tokens.acquire()
        else:
            self.wait()

    def release(self):
        """Release concurrent resources if acquired.

        This behavior will fall back to do nothing if there are no concurrent
        resources.
        """
        if hasattr(self, 'tokens'):
            self.tokens.release()

    def _generate(
        self,
        input: str or PromptList,
        max_out_len: int = 512,
    ) -> str:
        """Generate results given an input.

        Args:
            inputs (str or PromptList): A string or PromptDict.
                The PromptDict should be organized in OpenCompass'
                API format.
            max_out_len (int): The maximum length of the output.

        Returns:
            str: The generated string.
        """
        assert isinstance(input, (str, PromptList))

        if isinstance(input, str):
            messages = [{
                'sender_type': 'USER',
                'sender_name': 'OpenCompass',
                'text': input
            }]
        else:
            messages = []
            for item in input:
                msg = {'text': item['prompt']}
                if item['role'] == 'HUMAN':
                    msg['sender_type'] = 'USER'
                    msg['sender_name'] = 'OpenCompass'
                elif item['role'] == 'BOT':
                    msg['sender_type'] = 'BOT'
                    msg['sender_name'] = 'MM智能助理'

                messages.append(msg)

        data = {
            'bot_setting': [{
                'bot_name':
                'MM智能助理',
                'content':
                'MM智能助理是一款由MiniMax自研的，没有调用其他产品的接口的大型语言模型。' +
                'MiniMax是一家中国科技公司，一直致力于进行大模型相关的研究。'
            }],
            'reply_constraints': {
                'sender_type': 'BOT',
                'sender_name': 'MM智能助理'
            },
            'model':
            self.model,
            'messages':
            messages
        }

        max_num_retries = 0
        while max_num_retries < self.retry:
            self.acquire()
            raw_response = requests.request('POST',
                                            url=self.url,
                                            headers=self.headers,
                                            json=data)
            response = raw_response.json()
            self.release()

            if response is None:
                print('Connection error, reconnect.')
                # if connect error, frequent requests will casuse
                # continuous unstable network, therefore wait here
                # to slow down the request
                self.wait()
                continue
            if raw_response.status_code == 200:
                # msg = json.load(response.text)
                # response
                msg = response['reply']
                return msg
            # sensitive content, prompt overlength, network error
            # or illegal prompt
            if (response.status_code == 1000 or response.status_code == 1001
                    or response.status_code == 1002
                    or response.status_code == 1004
                    or response.status_code == 1008
                    or response.status_code == 1013
                    or response.status_code == 1027
                    or response.status_code == 1039
                    or response.status_code == 2013):
                print(response.text)
                return ''
            print(response)
            max_num_retries += 1

        raise RuntimeError(response.text)
