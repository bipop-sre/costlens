"""CostLens AI Agent core - LLM orchestration with tool calling."""

from __future__ import annotations

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from costlens.agent.tools.registry import ToolRegistry
from costlens.analysis.analyzer import CostAnalyzer
from costlens.config import Settings, get_settings
from costlens.models.budget import Budget

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个专业的 CostLens（云财务管理）AI 助手。你的核心职责是帮助企业监控和分析公有云成本。

## 你的能力
- 多云成本查询：查询 AWS、Azure、GCP、阿里云等平台的成本数据
- 成本趋势分析：分析历史成本趋势、环比同比变化
- 异常检测：自动发现成本突增、突降等异常情况
- 预算管理：监控预算执行情况，预测超支风险

## 回答规范
- 使用中文回答，保持专业但简洁的语气
- 对于成本数据，始终带上单位和时间范围
- 当数据不足时，明确说明局限性
- **必须使用 Markdown 格式**，使用以下格式：
  - 标题用 `##` 或 `###`
  - 重要数字用 `**加粗**`
  - 列表用 `-` 或 `1. 2. 3.`
  - 表格用 `| col1 | col2 |`
  - 代码或数值用反引号 `` ` ``

## 【严格遵守的回答格式规则】
1. **只回答用户明确询问的问题**
2. **禁止在回答末尾添加任何通用建议、优化建议、降本建议**
3. **禁止使用以下句式**：
   - "您可以..."
   - "建议..."
   - "如果需要..."
   - "另外..."
   - "此外..."
   - "希望这对您有帮助"
   - "如有其他问题..."
4. **回答必须直接、简洁，给出数据后立即结束，不追加任何额外说明**
5. **不要提供用户未询问的信息**

## 工具使用
当用户询问成本相关问题时，优先使用工具获取实时数据，不要凭记忆回答。
可以同时调用多个工具来综合分析。

### 工具调用强制规则（最高优先级，违反即为严重错误）
- **你绝对不能凭空提供任何费用数字**。每一个金额、百分比、排名都必须来自工具返回结果。
- 当用户询问任何成本相关问题时，**你必须先调用工具**，然后基于工具返回的数据回答。
- 如果工具未被调用就回复包含金额的内容，该回复是错误的。

### 工具选择规则
- **查询任何历史月份（含"X月""上月""Q2"等）的成本、排名、Top产品** → 必须使用 query_monthly_cost_from_db
  - 返回字段：total_cost（总成本）、top_services（Top10产品排名）、providers（各厂商明细）
  - 用户追问"前五名""排名""明细"时，直接读取已返回的 top_services 字段
- **仅当用户查询"今天""实时""当前"的数据** → 可使用 get_cost_summary
- 不确定用哪个工具时，优先使用 query_monthly_cost_from_db
"""

SYSTEM_PROMPT_EN = """You are a professional CostLens AI assistant. Your core mission is to help enterprises monitor and analyze public cloud costs.

## Your Capabilities
- Multi-cloud cost queries: AWS, Azure, GCP, Alibaba Cloud
- Cost trend analysis: historical trends, MoM/YoY changes
- Anomaly detection: automatic cost spike/drop detection
- Budget management: monitor budget execution and forecast overspend risks

## Response Guidelines
- Use English, keep it professional and concise
- Always include units and time ranges for cost data
- Clearly state limitations when data is insufficient
- **IMPORTANT: Only answer the user's specific question. Do NOT proactively provide optimization suggestions, cost reduction recommendations, or other unsolicited advice**
- **Do NOT add generic suggestions like "You can...", "We recommend...", "If you need..."**
- **Do NOT append additional notes or suggestions after your answer**

## Tool Usage
Always use tools to fetch real-time data rather than relying on memory.
You can invoke multiple tools for comprehensive analysis.
"""


class CostLensAgent:
    """Main CostLens agent with LLM-powered tool calling."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.analyzer = CostAnalyzer(self.settings)
        self.tool_registry = ToolRegistry(self.analyzer)
        self._client = AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
        )
        from datetime import datetime
        current_date = datetime.now().strftime("%Y-%m-%d")
        base_prompt = (
            SYSTEM_PROMPT if self.settings.agent_language.value == "zh-CN"
            else SYSTEM_PROMPT_EN
        )
        date_prefix = f"当前日期：{current_date}\n\n" if self.settings.agent_language.value == "zh-CN" else f"Current date: {current_date}\n\n"
        self._system_prompt = date_prefix + base_prompt

    def set_budgets(self, budgets: list[Budget]) -> None:
        self.tool_registry.set_budgets(budgets)

    async def chat(
        self,
        message: str,
        history: Optional[list[dict]] = None,
        max_tool_calls: int = 5,
    ) -> str:
        """Process a user message and return the agent's response."""
        messages = [{"role": "system", "content": self._system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})

        tools = self.tool_registry.get_openai_tools()
        tool_call_count = 0

        while tool_call_count < max_tool_calls:
            response = await self._client.chat.completions.create(
                model=self.settings.openai_model,
                messages=messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
                temperature=0.3,
            )

            choice = response.choices[0]
            assistant_message = choice.message

            if not assistant_message.tool_calls:
                raw_content = assistant_message.content or ""
                # Guard: if response contains cost figures but no tool was called, force retry
                import re as _re
                cost_patterns = [r'\d[\d,]*\.?\d*\s*CNY', r'\d[\d,]*\.?\d*\s*元', r'成本为', r'花费']
                has_cost_figure = any(_re.search(p, raw_content) for p in cost_patterns)
                if has_cost_figure and tool_call_count == 0 and tools:
                    logger.warning("LLM returned cost figures without calling any tool, forcing retry with tool hint")
                    messages.append({"role": "assistant", "content": raw_content})
                    messages.append({"role": "user", "content": "请调用工具查询真实数据，不要编造数字。"})
                    tool_call_count = max_tool_calls - 1  # allow one more iteration
                    continue
                return raw_content

            messages.append(assistant_message.model_dump())

            for tool_call in assistant_message.tool_calls:
                tool_call_count += 1
                func_name = tool_call.function.name
                try:
                    func_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    func_args = {}

                logger.info("Tool call: %s(%s)", func_name, func_args)
                result = await self.tool_registry.execute(func_name, func_args)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        response = await self._client.chat.completions.create(
            model=self.settings.openai_model,
            messages=messages,
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    async def stream_chat(
        self,
        message: str,
        history: Optional[list[dict]] = None,
        max_tool_calls: int = 5,
    ):
        """Process a user message and stream the response."""
        messages = [{"role": "system", "content": self._system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})

        tools = self.tool_registry.get_openai_tools()
        tool_call_count = 0

        while tool_call_count < max_tool_calls:
            response = await self._client.chat.completions.create(
                model=self.settings.openai_model,
                messages=messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
                temperature=0.3,
            )

            choice = response.choices[0]
            assistant_message = choice.message

            if not assistant_message.tool_calls:
                stream = await self._client.chat.completions.create(
                    model=self.settings.openai_model,
                    messages=messages,
                    temperature=0.3,
                    stream=True,
                )
                async for chunk in stream:
                    if chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                return

            messages.append(assistant_message.model_dump())

            for tool_call in assistant_message.tool_calls:
                tool_call_count += 1
                func_name = tool_call.function.name
                try:
                    func_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    func_args = {}

                logger.info("Tool call: %s(%s)", func_name, func_args)
                result = await self.tool_registry.execute(func_name, func_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        stream = await self._client.chat.completions.create(
            model=self.settings.openai_model,
            messages=messages,
            temperature=0.3,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def close(self) -> None:
        await self.analyzer.close()
