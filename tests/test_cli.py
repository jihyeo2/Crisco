from extract.__main__ import parse_pages
from extract.llm import Usage


def test_parse_pages():
    assert parse_pages("28-30") == [28, 29, 30]
    assert parse_pages("3-5,9,4") == [3, 4, 5, 9]


def test_usage_adds_and_prices():
    total = Usage(1_000_000, 0) + Usage(0, 100_000)
    assert (total.input_tokens, total.output_tokens) == (1_000_000, 100_000)
    assert round(total.cost_usd, 2) == 3.00  # $2 in + $1 out at Sonnet 5 rates
