from prometheus_client import Counter

GET_TOKEN_COUNTER = Counter("get_token_counter", "Total count of get jwt token calls")
