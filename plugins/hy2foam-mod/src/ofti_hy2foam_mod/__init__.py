"""OFTI plugin for the modified / NN-fork of hy2Foam.

This plugin owns everything the stock solver lacks (NN / NNcompiled models,
precompiledModel, and the stateInputOrder/inputOrder/outputOrder species/state
ordering keys). The stock `ofti-hy2foam` plugin stays free of these keys.
"""
