.PHONY: install today flow signals report dashboard backfill list

install:
	pip3 install -r requirements.txt --break-system-packages

today:
	python3 -m ntw.cli today

flow:
	python3 -m ntw.cli flow --days 30

signals:
	python3 -m ntw.cli signals --days 30

report:
	python3 -m ntw.cli report

dashboard:
	python3 -m ntw.cli dashboard

backfill:
	python3 -m ntw.cli backfill

list:
	python3 -m ntw.cli list

all:
	python3 -m ntw.cli report
	open reports/
