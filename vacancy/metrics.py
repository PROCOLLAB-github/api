from prometheus_client import Counter

VACANCIES_RESPONSE_COUNTER = Counter(
    "vacancies_response_counter", "Total number of responses for vacancies"
)
