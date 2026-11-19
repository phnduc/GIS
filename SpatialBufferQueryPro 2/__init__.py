# -*- coding: utf-8 -*-
def classFactory(iface):
    from .spatial_buffer_query import SpatialBufferQueryPlugin
    return SpatialBufferQueryPlugin(iface)
