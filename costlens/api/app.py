"""FastAPI application for CostLens."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from costlens.agent.chat import ChatSession
from costlens.agent.core import CostLensAgent
from costlens.analysis.analyzer import CostAnalyzer
from costlens.config import get_settings
from costlens.models.budget import Budget

logger = logging.getLogger(__name__)
_sessions: dict[str, ChatSession] = {}
_agent: Optional[CostLensAgent] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _agent
    settings = get_settings()
    _agent = CostLensAgent(settings)
    logger.info("CostLens started with providers: %s", settings.enabled_providers)
    yield
    if _agent:
        await _agent.close()


from costlens.api.storage_routes import router as storage_router
app = FastAPI(
    title="CostLens AI Agent",
    description="AI-powered multi-cloud cost monitoring and optimization agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(storage_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    stream: bool = False


class ChatResponse(BaseModel):
    session_id: str
    response: str


class BudgetRequest(BaseModel):
    name: str
    amount: float
    currency: str = "USD"
    period: str = "monthly"
    provider: Optional[str] = None
    service_name: Optional[str] = None


class AnalysisRequest(BaseModel):
    days: int = 30
    provider: Optional[str] = None


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """Send a message to the CostLens agent."""
    session_id = request.session_id or str(uuid.uuid4())

    if session_id not in _sessions:
        _sessions[session_id] = ChatSession(session_id=session_id, agent=_agent)

    session = _sessions[session_id]

    if request.stream:
        async def generate():
            async for token in session.stream_send(request.message):
                yield f"data: {token}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(generate(), media_type="text/event-stream")

    response = await session.send(request.message)
    return ChatResponse(session_id=session_id, response=response)


@app.get("/api/sessions/{session_id}/history")
async def get_session_history(session_id: str):
    """Get chat session history."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "history": _sessions[session_id].get_history()}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a chat session."""
    if session_id in _sessions:
        del _sessions[session_id]
    return {"status": "ok"}


@app.get("/api/cost/summary")
async def get_cost_summary(days: int = 30, provider: Optional[str] = None):
    """Get cost summary for the specified period."""
    end = date.today()
    start = end - timedelta(days=days)

    analyzer = CostAnalyzer()
    try:
        if provider:
            connector = await analyzer._get_connector(provider)
            summary = await connector.get_cost_summary(start, end)
            return summary.model_dump()
        return await analyzer.get_multi_cloud_summary(start, end)
    finally:
        await analyzer.close()


@app.get("/api/cost/analysis")
async def run_analysis(days: int = 30):
    """Run full cost analysis pipeline."""
    end = date.today()
    start = end - timedelta(days=days)

    analyzer = CostAnalyzer()
    try:
        result = await analyzer.analyze(start, end)
        return result
    finally:
        await analyzer.close()


@app.get("/api/cost/anomalies")
async def detect_anomalies(days: int = 30):
    """Detect cost anomalies."""
    end = date.today()
    start = end - timedelta(days=days)

    analyzer = CostAnalyzer()
    try:
        all_records = []
        for p in analyzer.settings.get_enabled_providers():
            connector = await analyzer._get_connector(p.value)
            records = await connector.get_cost_data(start, end)
            all_records.extend(records)
        alerts = analyzer.anomaly_detector.detect_anomalies(all_records)
        return {"anomalies": [a.model_dump() for a in alerts], "count": len(alerts)}
    finally:
        await analyzer.close()


@app.get("/api/cost/recommendations")
async def get_recommendations(days: int = 30):
    """Get optimization recommendations."""
    end = date.today()
    start = end - timedelta(days=days)

    analyzer = CostAnalyzer()
    try:
        all_recs = []
        for p in analyzer.settings.get_enabled_providers():
            connector = await analyzer._get_connector(p.value)
            records = await connector.get_cost_data(start, end)
            recs = analyzer.optimizer.generate_recommendations(records, p.value)
            all_recs.extend(recs)
        total_savings = sum(r.estimated_saving for r in all_recs)
        return {
            "recommendations": [r.model_dump() for r in all_recs],
            "total_potential_savings": round(total_savings, 2),
        }
    finally:
        await analyzer.close()


@app.get("/api/cost/trends")
async def get_trends(days: int = 30):
    """Get cost trends analysis."""
    end = date.today()
    start = end - timedelta(days=days)

    analyzer = CostAnalyzer()
    try:
        all_records = []
        for p in analyzer.settings.get_enabled_providers():
            connector = await analyzer._get_connector(p.value)
            records = await connector.get_cost_data(start, end)
            all_records.extend(records)
        trend = analyzer.trend_analyzer.analyze_daily_trend(all_records)
        forecast = analyzer.trend_analyzer.forecast(all_records)
        return {"trend": trend, "forecast": forecast}
    finally:
        await analyzer.close()


@app.post("/api/budgets")
async def create_budget(request: BudgetRequest):
    """Create or update a budget."""
    budget = Budget(
        name=request.name,
        amount=request.amount,
        currency=request.currency,
        period=request.period,
        provider=request.provider,
        service_name=request.service_name,
    )
    return {"status": "created", "budget": budget.model_dump()}


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    settings = get_settings()
    return {
        "status": "healthy",
        "version": "0.1.0",
        "providers": settings.enabled_providers,
        "model": settings.openai_model,
    }


@app.get("/metrics")
async def metrics_endpoint():
    """Prometheus metrics endpoint."""
    from costlens.metrics import get_metrics_collector
    from fastapi.responses import PlainTextResponse

    collector = get_metrics_collector()
    metrics_text = await collector.collect()
    return PlainTextResponse(content=metrics_text, media_type="text/plain; version=0.0.4")
