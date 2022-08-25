from abc import abstractmethod, ABC
from typing import Iterable, Optional, Set


class AbstractClient(ABC):

    class User(ABC):
        nick: str
        userhost: str
        modes: Set[str]
        joined: float
        pass


    @abstractmethod
    def chanmsg(self, text: str) -> None:
        pass

    @abstractmethod
    def notice(self, target: str, text: str) -> None:
        pass

    @abstractmethod
    def match_user(self, nick: str, userhost: str) -> bool:
        pass

    @abstractmethod
    def bot_has_ops(self) -> bool:
        pass

    @abstractmethod
    def grant_voice(self, *targets: str) -> None:
        pass

    @abstractmethod
    def revoke_voice(self, *targets: str) -> None:
        pass

    @abstractmethod
    def set_channel_voices(self, voiced_nicks: Iterable[str]) -> None:
        pass

    @abstractmethod
    def writeq_len(self) -> int:
        pass

    @abstractmethod
    def writeq_bytes(self) -> int:
        pass

    @abstractmethod
    def clear_writeq(self) -> None:
        pass


    @abstractmethod
    def servername(self) -> str:
        pass


    @abstractmethod
    def bytes_sent(self) -> int:
        pass


    @abstractmethod
    def bytes_received(self) -> int:
        pass


    @abstractmethod
    def user_exists(self, nick: str) -> bool:
        pass

    @abstractmethod
    def nick_userhost(self, nick: str) -> Optional[str]:
        pass

    @abstractmethod
    def is_bot_nick(self, nick: str) -> bool:
        pass

    @abstractmethod
    def quit(self, text: str) -> None:
        pass


class AbstractBot(ABC):

    @abstractmethod
    def connected(self, client: AbstractClient) -> None:
        pass

    @abstractmethod
    def disconnected(self) -> None:
        pass

    @abstractmethod
    def ready(self) -> None:
        pass

    @abstractmethod
    def acquired_ops(self) -> None:
        pass

    @abstractmethod
    def nick_parted(self, user: AbstractClient.User) -> None:
        pass

    @abstractmethod
    def nick_kicked(self, user: AbstractClient.User) -> None:
        pass

    @abstractmethod
    def netsplit(self, user: AbstractClient.User) -> None:
        pass

    @abstractmethod
    def nick_dropped(self, user: AbstractClient.User) -> None:
        pass

    @abstractmethod
    def nick_quit(self, user: AbstractClient.User) -> None:
        pass

    @abstractmethod
    def nick_changed(self, user: AbstractClient.User, new_nick: str) -> None:
        pass

    @abstractmethod
    def private_message(self, user: AbstractClient.User, text: str) -> None:
        pass

    @abstractmethod
    def channel_message(self, user: AbstractClient.User, text: str) -> None:
        pass

    @abstractmethod
    def channel_notice(self, user: AbstractClient.User, text: str) -> None:
        pass


AbstractClient.register(tuple)
AbstractBot.register(tuple)
