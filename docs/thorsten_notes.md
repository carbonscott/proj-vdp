```jupyter
In [1]: from tiled.client import from_uri

In [2]: client = from_uri("https://lcls-data-portal.slac.stanford.edu/tiled-dev", api_key="XXXXXXXX")

In [3]: client.items()
Out[3]: <ItemsView>

In [4]: client.item
Out[4]: 
{'id': '',
 'attributes': {'ancestors': [],
  'structure_family': 'container',
  'specs': [],
  'metadata': {},
  'structure': {'contents': None, 'count': 6},
  'access_blob': {},
  'sorting': [{'key': '', 'direction': 1}],
  'data_sources': None},
 'links': {'self': 'https://lcls-data-portal.slac.stanford.edu/tiled-dev/api/v1/metadata/',
  'search': 'https://lcls-data-portal.slac.stanford.edu/tiled-dev/api/v1/search/',
  'full': 'https://lcls-data-portal.slac.stanford.edu/tiled-dev/api/v1/container/full/'},
 'meta': None}

In [5]: quit
```
