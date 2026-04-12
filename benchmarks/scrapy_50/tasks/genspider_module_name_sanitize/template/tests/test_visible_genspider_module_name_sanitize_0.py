from scrapy.commands.genspider import sanitize_module_name

def test_hyphen_replaced_with_underscore():
    assert sanitize_module_name('my-spider') == 'my_spider'

def test_dot_replaced_with_underscore():
    assert sanitize_module_name('my.spider') == 'my_spider'
