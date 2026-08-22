from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .core.config import settings
from .core.database import engine
from .models import models
from .api.endpoints import users, fitness, chat, tracking, feedback

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(fitness.router, prefix="/api/fitness", tags=["fitness"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(tracking.router, prefix="/api/tracking", tags=["tracking"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"])

@app.get("/")
def read_root():
    return {"message": "Fitness AI Backend is running!"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}