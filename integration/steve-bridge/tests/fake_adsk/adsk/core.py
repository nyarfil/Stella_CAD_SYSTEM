"""Fake adsk.core: only the base classes and enums that STEVE's fusion_tools touches."""


class _Handler:
    def __init__(self):
        pass


class CustomEventHandler(_Handler):
    pass


class DocumentEventHandler(_Handler):
    pass


class ApplicationCommandEventHandler(_Handler):
    pass


class CommandCreatedEventHandler(_Handler):
    pass


class CommandEventHandler(_Handler):
    pass


class CommandTerminationReason:
    CompletedTerminationReason = 1
    CancelledTerminationReason = 2


class ViewOrientations:
    FrontViewOrientation = "front"
    TopViewOrientation = "top"
    RightViewOrientation = "right"
    LeftViewOrientation = "left"
    BackViewOrientation = "back"
    BottomViewOrientation = "bottom"
    IsoTopRightViewOrientation = "iso"
