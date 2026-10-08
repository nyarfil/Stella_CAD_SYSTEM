"""Nominal B-rep measurement, independent of cached display triangulation."""


def nominal_bounds(shape):
    """Return xmin,ymin,zmin,xmax,ymax,zmax from underlying geometry.

    OCCT still uses its numerical algorithms; this is not physical metrology.
    Cached tessellation can expand CadQuery's default box by mesh deflection.
    Do not let rendering change a dimensional verdict on the same solid.
    """
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    box=Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped,box,False,False)
    return tuple(float(value) for value in box.Get())
