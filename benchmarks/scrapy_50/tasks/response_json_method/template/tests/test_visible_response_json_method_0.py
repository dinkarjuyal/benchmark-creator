from scrapy.http import TextResponse

def test_response_json_dict():
    r = TextResponse('https://api.example.com/', body=b'{"key": "value"}',
                      encoding='utf-8')
    data = r.json()
    assert data == {'key': 'value'}

def test_response_json_list():
    r = TextResponse('https://api.example.com/', body=b'[1, 2, 3]',
                      encoding='utf-8')
    assert r.json() == [1, 2, 3]
