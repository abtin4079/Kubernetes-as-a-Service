FROM python:3.9.19-alpine

WORKDIR /app
COPY . /app

RUN pip install fastapi
RUN pip install requests
RUN pip install pydantic
RUN pip install uvicorn
RUN pip install kuberntes
RUN pip install redis
RUN pip install python-dotenv

EXPOSE 7001
EXPOSE 6969


CMD ["python", "service1-kuber.py"]