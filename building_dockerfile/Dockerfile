FROM python:3.9.1-buster

WORKDIR /app
COPY . /app

RUN pip install --upgrade pip
COPY ./requirements.txt /var/app
RUN pip install -r requirements.txt


EXPOSE 7001
EXPOSE 6969


CMD ["python", "service1-kuber.py"]