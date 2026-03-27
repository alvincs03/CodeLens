from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from database import Base

class Submission(Base):
  __tablename__ = "submissions"
  id = Column(Integer, primary_key=True, index=True)
  code = Column(Text, nullable=False)
  language = Column(String, nullable=True)
  explanation = Column(Text, nullable=True)
  bugs = Column(Text, nullable=True)
  suggestions = Column(Text, nullable=True)
  score = Column(Integer, nullable=True)
  complexity = Column(Text, nullable=True)
  security = Column(Text, nullable=True)
  score_reasoning = Column(Text, nullable=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now())

class FileAnalysis(Base):
  __tablename__ = "file_analyses"
  id = Column(Integer, primary_key=True, index=True)
  content_hash = Column(String(64), nullable=False, unique=True, index=True)
  filename = Column(String, nullable=True)
  summary = Column(Text, nullable=True)
  tech = Column(Text, nullable=True)
  concepts = Column(Text, nullable=True)
  purpose = Column(Text, nullable=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now())