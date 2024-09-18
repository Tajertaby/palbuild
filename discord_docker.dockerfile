FROM python:3.13.0rc2-bookworm
WORKDIR /bot
COPY . /bot
RUN pip install -r requirements.txt
CMD main.py