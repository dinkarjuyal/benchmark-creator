from scrapy import Selector

def test_css_returns_selector_list():
    sel = Selector(text='<div class="item"><p>Hello</p></div>')
    result = sel.css('div.item p')
    assert hasattr(result, 'getall'), (
        f"Expected SelectorList, got {type(result).__name__}"
    )
    texts = result.css('::text').getall()
    assert 'Hello' in texts
