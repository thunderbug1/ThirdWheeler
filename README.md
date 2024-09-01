# ThirdWheeler

ThirdWheeler is a Telegram bot designed to improve communication between couples. The bot acts as a helpful assistant, offering reminders and suggestions based on what each partner would like to see more or less often. The bot stores conversations and user information in a PostgreSQL database, and it’s powered by a locally hosted Llama 3.1 language model using Ollama.

## Features

- **Partner Linking**: Users can link with their partners via a username or invite link.
- **Scheduled Reminders**: The bot can schedule reminders and actions based on user input and stored preferences.
- **Localized Communication**: The bot detects the user's preferred language and translates system messages accordingly.
- **Data Privacy**: Users can delete all their data or unlink from their partner at any time, with confirmations to prevent accidental actions.

## Tech Stack

- **Python 3.12**
- **Telegram Bot API**: Using `python-telegram-bot` library.
- **PostgreSQL**: Database to store user information, conversations, and scheduled actions.
- **SQLAlchemy**: ORM for interacting with the PostgreSQL database.
- **Alembic**: Database migration tool (optional, but recommended).
- **Ollama**: Hosts the Llama 3.1 language model locally.
- **Docker**: For containerization, including a PostgreSQL database and the bot itself.

## Getting Started

### Prerequisites

- **Python 3.12**
- **Docker** and **Docker Compose**
- **PostgreSQL** database or use the Docker setup for PostgreSQL
- **Ollama**: To host the Llama 3.1 model locally

### Installation

1. **Clone the Repository**

   ```bash
   git clone https://github.com/thunderbug1/ThirdWheeler.git
   cd ThirdWheeler

2. **start olama locally**

   ```bash 
   ollama serve

3. **start docker compose**

   ```bash 
   docker compose up -d