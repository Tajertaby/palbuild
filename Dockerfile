FROM python:3.12.6-bookworm
WORKDIR /bot
COPY . /bot
RUN pip install -r requirements.txt
CMD ["python", "main.py"]