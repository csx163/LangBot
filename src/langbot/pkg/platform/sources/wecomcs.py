from __future__ import annotations
import typing
import asyncio
import traceback

import datetime
import pydantic

from langbot.libs.wecom_customer_service_api.api import WecomCSClient
import langbot_plugin.api.definition.abstract.platform.adapter as abstract_platform_adapter
from langbot.libs.wecom_customer_service_api.wecomcsevent import WecomCSEvent
import langbot_plugin.api.entities.builtin.platform.entities as platform_entities
import langbot_plugin.api.entities.builtin.platform.message as platform_message
import langbot_plugin.api.entities.builtin.platform.events as platform_events
from langbot_plugin.api.entities.builtin.command import errors as command_errors
import langbot_plugin.api.definition.abstract.platform.event_logger as abstract_platform_logger


class WecomMessageConverter(abstract_platform_adapter.AbstractMessageConverter):
    @staticmethod
    async def yiri2target(message_chain: platform_message.MessageChain, bot: WecomCSClient):
        content_list = []

        for msg in message_chain:
            if type(msg) is platform_message.Plain:
                content_list.append(
                    {
                        'type': 'text',
                        'content': msg.text,
                    }
                )
            elif type(msg) is platform_message.Image:
                content_list.append(
                    {
                        'type': 'image',
                        'media_id': await bot.get_media_id(msg),
                    }
                )
            elif type(msg) is platform_message.Forward:
                for node in msg.node_list:
                    content_list.extend((await WecomMessageConverter.yiri2target(node.message_chain, bot)))
            else:
                content_list.append(
                    {
                        'type': 'text',
                        'content': str(msg),
                    }
                )

        return content_list

    @staticmethod
    async def target2yiri(message: str, message_id: int = -1):
        yiri_msg_list = []
        yiri_msg_list.append(platform_message.Source(id=message_id, time=datetime.datetime.now()))

        yiri_msg_list.append(platform_message.Plain(text=message))
        chain = platform_message.MessageChain(yiri_msg_list)

        return chain

    @staticmethod
    async def target2yiri_image(picurl: str, message_id: int = -1):
        yiri_msg_list = []
        yiri_msg_list.append(platform_message.Source(id=message_id, time=datetime.datetime.now()))
        yiri_msg_list.append(platform_message.Image(base64=picurl))
        chain = platform_message.MessageChain(yiri_msg_list)

        return chain


class WecomEventConverter(abstract_platform_adapter.AbstractEventConverter):
    @staticmethod
    async def yiri2target(event: platform_events.Event, bot_account_id: int, bot: WecomCSClient) -> WecomCSEvent:
        # only for extracting user information

        if type(event) is platform_events.GroupMessage:
            pass

        if type(event) is platform_events.FriendMessage:
            return event.source_platform_object

    @staticmethod
    async def target2yiri(event: WecomCSEvent):
        """
        将 WecomEvent 转换为平台的 FriendMessage 对象。

        Args:
            event (WecomEvent): 企业微信客服事件。

        Returns:
            platform_events.FriendMessage: 转换后的 FriendMessage 对象。
        """
        # 转换消息链
        if event.type == 'text':
            yiri_chain = await WecomMessageConverter.target2yiri(event.message, event.message_id)
            friend = platform_entities.Friend(
                id=f'u{event.user_id}',
                nickname=str(event.user_id),
                remark='',
            )

            return platform_events.FriendMessage(
                sender=friend, message_chain=yiri_chain, time=event.timestamp, source_platform_object=event
            )
        elif event.type == 'image':
            friend = platform_entities.Friend(
                id=f'u{event.user_id}',
                nickname=str(event.user_id),
                remark='',
            )

            yiri_chain = await WecomMessageConverter.target2yiri_image(picurl=event.picurl, message_id=event.message_id)

            return platform_events.FriendMessage(
                sender=friend, message_chain=yiri_chain, time=event.timestamp, source_platform_object=event
            )
        elif event.type == 'merged_msg':
            # 处理合并聊天记录
            print(f"[DEBUG] 处理合并消息,原始数据: {event.merged_msg}")
            items = event.merged_items or []
            print(f"[DEBUG] 解析后的 items 数量: {len(items)}")
            print(f"[DEBUG] items 内容: {items}")
            content_parts = []
            
            # 添加标题
            if event.merged_msg and event.merged_msg.get('title'):
                content_parts.append(f"=== {event.merged_msg['title']} ===")
            
            # 提取每条消息的内容
            for idx, item in enumerate(items):
                print(f"[DEBUG] 处理第 {idx+1} 条消息,完整数据: {item}")
                
                # msg_content 已经被 merged_items 属性解析为字典
                msg_content = item.get('msg_content', {})
                msg_type = msg_content.get('msgtype', '') if isinstance(msg_content, dict) else ''
                
                print(f"[DEBUG] msg_content: {msg_content}, msgtype: {msg_type}")
                
                if msg_type == 'text':
                    # 文本消息:从 msg_content.text.content 提取内容
                    text_obj = msg_content.get('text', {})
                    content = text_obj.get('content', '') if isinstance(text_obj, dict) else ''
                    if content:
                        content_parts.append(content)
                        print(f"[DEBUG] 提取到文本内容: {content}")
                elif msg_type == 'image':
                    # 图片消息:显示标识
                    content_parts.append('[图片]')
                elif msg_type == 'file':
                    # 文件消息:显示文件名
                    file_obj = msg_content.get('file', {})
                    filename = file_obj.get('filename', '文件') if isinstance(file_obj, dict) else '文件'
                    content_parts.append(f'[文件: {filename}]')
                elif msg_type == 'voice':
                    # 语音消息:显示标识
                    content_parts.append('[语音]')
                elif msg_type == 'video':
                    # 视频消息:显示标识
                    content_parts.append('[视频]')
                elif msg_type:
                    # 其他已知类型:显示类型
                    content_parts.append(f'[{msg_type}]')
                else:
                    # 未知类型:尝试直接显示 item 的字符串表示
                    print(f"[DEBUG] 未知消息类型,item 完整内容: {item}")
            
            # 合并所有内容
            merged_content = '\n'.join(content_parts)
            print(f"[DEBUG] 最终合并内容: {merged_content}")
            print(f"[DEBUG] 合并内容长度: {len(merged_content)}")
            
            # 创建消息链
            yiri_chain = await WecomMessageConverter.target2yiri(merged_content, event.message_id)
            
            # 创建 Friend 对象
            friend = platform_entities.Friend(
                id=f'u{event.user_id}',
                nickname=str(event.user_id),
                remark='',
            )
            
            return platform_events.FriendMessage(
                sender=friend, message_chain=yiri_chain, time=event.timestamp, source_platform_object=event
            )


class WecomCSAdapter(abstract_platform_adapter.AbstractMessagePlatformAdapter):
    bot: WecomCSClient = pydantic.Field(exclude=True)
    message_converter: WecomMessageConverter = WecomMessageConverter()
    event_converter: WecomEventConverter = WecomEventConverter()
    bot_uuid: str = None

    def __init__(self, config: dict, logger: abstract_platform_logger.AbstractEventLogger):
        required_keys = [
            'corpid',
            'secret',
            'token',
            'EncodingAESKey',
        ]
        missing_keys = [key for key in required_keys if key not in config]
        if missing_keys:
            raise command_errors.ParamNotEnoughError('企业微信客服缺少相关配置项，请查看文档或联系管理员')

        bot = WecomCSClient(
            corpid=config['corpid'],
            secret=config['secret'],
            token=config['token'],
            EncodingAESKey=config['EncodingAESKey'],
            logger=logger,
            unified_mode=True,
        )

        super().__init__(
            config=config,
            logger=logger,
            bot_account_id='',
            listeners={},
            bot=bot,
        )

    async def reply_message(
        self,
        message_source: platform_events.MessageEvent,
        message: platform_message.MessageChain,
        quote_origin: bool = False,
    ):
        Wecom_event = await WecomEventConverter.yiri2target(message_source, self.bot_account_id, self.bot)
        content_list = await WecomMessageConverter.yiri2target(message, self.bot)

        for content in content_list:
            if content['type'] == 'text':
                await self.bot.send_text_msg(
                    open_kfid=Wecom_event.receiver_id,
                    external_userid=Wecom_event.user_id,
                    msgid=Wecom_event.message_id,
                    content=content['content'],
                )

    async def send_message(self, target_type: str, target_id: str, message: platform_message.MessageChain):
        pass

    def set_bot_uuid(self, bot_uuid: str):
        """设置 bot UUID（用于生成 webhook URL）"""
        self.bot_uuid = bot_uuid

    def register_listener(
        self,
        event_type: typing.Type[platform_events.Event],
        callback: typing.Callable[
            [platform_events.Event, abstract_platform_adapter.AbstractMessagePlatformAdapter], None
        ],
    ):
        async def on_message(event: WecomCSEvent):
            self.bot_account_id = event.receiver_id
            try:
                return await callback(await self.event_converter.target2yiri(event), self)
            except Exception:
                await self.logger.error(f'Error in wecomcs callback: {traceback.format_exc()}')

        if event_type == platform_events.FriendMessage:
            self.bot.on_message('text')(on_message)
            self.bot.on_message('image')(on_message)
            self.bot.on_message('merged_msg')(on_message)  # 添加合并消息支持
        elif event_type == platform_events.GroupMessage:
            pass

    async def handle_unified_webhook(self, bot_uuid: str, path: str, request):
        """处理统一 webhook 请求。

        Args:
            bot_uuid: Bot 的 UUID
            path: 子路径（如果有的话）
            request: Quart Request 对象

        Returns:
            响应数据
        """
        return await self.bot.handle_unified_webhook(request)

    async def run_async(self):
        # 统一 webhook 模式下，不启动独立的 Quart 应用
        # 保持运行但不启动独立端口

        async def keep_alive():
            while True:
                await asyncio.sleep(1)

        await keep_alive()

    async def kill(self) -> bool:
        return False

    async def is_muted(self, group_id: int) -> bool:
        return False

    async def unregister_listener(
        self,
        event_type: type,
        callback: typing.Callable[
            [platform_events.Event, abstract_platform_adapter.AbstractMessagePlatformAdapter], None
        ],
    ):
        return super().unregister_listener(event_type, callback)
