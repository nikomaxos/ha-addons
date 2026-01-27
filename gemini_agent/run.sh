#!/bin/bash

# Απενεργοποίηση του S6 check και άμεση εκτέλεση
echo "Starting Gemini AI Middleware Agent..."

# Run python unbuffered to see logs in real-time
python3 -u /agent.py