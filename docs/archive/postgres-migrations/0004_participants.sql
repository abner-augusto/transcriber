-- Migration 0004: Add participants column to meetings table
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS participants TEXT;
