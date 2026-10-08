"""Fake adsk.fusion."""


class Design:
    @staticmethod
    def cast(product):
        return product if getattr(product, "productType", None) == "DesignProductType" else None


class BRepBody:
    @staticmethod
    def cast(value):
        return value


class FeatureHealthStates:
    HealthyFeatureHealthState = 0
