from FreeCAD import Base
from .math import one_orthogonal_vector, projection_on_vector, projection_on_orthogonal_of_vector
from numpy import pi
from .logging_unit import logger


def orientation(u, v, w):
    det = u.dot(v.cross(w))
    if det >= 0:
        return +1
    else:
        return -1


def signed_angle(axis, v1, v2):
    """
    Computes the (signed) angle from v1 to v2, wrt the axis vector
    """
    angle = v1.getAngle(v2)
    angle *= orientation(axis, v1, v2)
    return angle


def axial_rotation_from_axis_and_angle(axis_origin, axis_dir, angle):
    """
    Returns a rotation with given axis and angle
    """
    z_axis = Base.Vector(0, 0, 1)
    local_cs = Base.Placement(axis_origin, Base.Rotation(z_axis, axis_dir))
    return local_cs.multiply(
        Base.Placement(Base.Vector(), Base.Rotation(angle * 180.0 / pi, 0, 0)).multiply(local_cs.inverse()))


def axial_rotation_from_vector_and_image(origin, vector0, vector1):
    """
    Returns a rotation that transforms the ray with origin and vector equals to vector0 to the ray with same
    origin and vector vector1.
    """
    try:
        normal = vector0.cross(vector1)
        normal.normalize()
    except Base.FreeCADError:
        # we assume now that the two vectors are collinear
        normal = one_orthogonal_vector(vector0)
    angle = vector0.getAngle(vector1)
    return axial_rotation_from_axis_and_angle(origin, normal, angle)


def get_labels(obj):
    label = obj.Label
    start = label.find("(")
    end = label.find(")")
    if start < 0 or end < 0:
        return []
    string = label[start + 1:end]
    return string.split(',')


class Joint:
    """
    Base class to represent joints
    """
    pass


class AxialJoint(Joint):
    """
    Class used to represent joints that rotate around an axis
    """
    def __init__(self, axis_origin, axis_vector):
        self.axis_origin = axis_origin
        self.axis_vector = axis_vector

    def compute_rotation_to_point(self, target, normal, light_direction):
        pointing = projection_on_orthogonal_of_vector(target-self.axis_origin, self.axis_vector)
        pointing.normalize()
        light_unit = projection_on_orthogonal_of_vector(light_direction, self.axis_vector)
        light_unit.normalize()
        desired_normal = pointing - light_unit
        angle = signed_angle(self.axis_vector, normal, desired_normal)  # normal.getAngle(desired_normal)
        return axial_rotation_from_axis_and_angle(self.axis_origin, self.axis_vector, angle)

    def compute_rotation_to_direction(self, normal, light_direction):
        light_unit = projection_on_orthogonal_of_vector(light_direction, self.axis_vector)
        light_unit.normalize()
        desired_normal = light_unit * (-1.0)
        angle = signed_angle(self.axis_vector, normal, desired_normal) # normal.getAngle(desired_normal)
        return axial_rotation_from_axis_and_angle(self.axis_origin, self.axis_vector, angle)


class CentralJoint(Joint):
    """
    Class used to represent joints that rotate around a point
    """

    def __init__(self, center):
        self.center = center

    def compute_rotation_to_point(self, target, normal, light_direction):
        pointing = target - self.center
        pointing.normalize()
        light_unit = light_direction * 1.0
        light_unit.normalize()
        desired_normal = pointing - light_unit
        return axial_rotation_from_vector_and_image(self.center, normal, desired_normal)

    def compute_rotation_to_direction(self, normal, light_direction):
        light_unit = light_direction * 1.0
        light_unit.normalize()
        desired_normal = light_unit * (-1.0)
        return axial_rotation_from_vector_and_image(self.center, normal, desired_normal)


class MultiTracking:
    def __init__(self, source_direction, scene):
        self.scene = scene
        self.source_direction = source_direction
        self.object_joint_map = {}
        self.object_normal_map = {}
        self.object_target_map = {}
        self.object_movements_map = {}
        self.get_data_from_objects()
        self.compute_movements()

    def get_joint_from_label(self, label):
        joint_obj = [obj2 for obj2 in self.scene.objects if obj2.Label == label][0]
        if joint_obj.Shape.ShapeType == "Vertex":
            center = joint_obj.Shape.Vertexes[0].Point
            return CentralJoint(center)
        elif joint_obj.Shape.ShapeType in ["Wire", "Edge"]:
            start = joint_obj.Shape.Vertexes[0].Point
            end = joint_obj.Shape.Vertexes[1].Point
            return AxialJoint(start, end - start)

    def get_normal_from_label(self, label):
        normal_obj = [obj2 for obj2 in self.scene.objects if obj2.Label == label][0]
        if normal_obj.Shape.ShapeType in ["Wire", "Edge"]:
            start = normal_obj.Shape.Vertexes[0].Point
            end = normal_obj.Shape.Vertexes[1].Point
            return end-start

    def get_target_from_label(self, label):
        target_obj = [obj2 for obj2 in self.scene.objects if obj2.Label == label][0]
        if target_obj.Shape.ShapeType == "Vertex":
            target = target_obj.Shape.Vertexes[0].Point
            return target

    def get_data_from_objects(self):
        for obj in self.scene.objects:
            labels = get_labels(obj)
            if len(labels) < 2:
                # no movement
                continue
            if len(labels) == 2:
                # gives joint but not normal
                raise Exception("Need to give joint and normal")
            self.object_joint_map[obj] = self.get_joint_from_label(labels[1])
            self.object_normal_map[obj] = self.get_normal_from_label(labels[2])
            if len(labels) == 3:
                # no target given
                self.object_target_map[obj] = None
            else:
                self.object_target_map[obj] = self.get_target_from_label(labels[3])

    def compute_movements(self):
        for obj in self.object_joint_map:
            joint = self.object_joint_map[obj]
            normal = self.object_normal_map[obj]
            target = self.object_target_map[obj]
            if target is None:
                # source tracking
                movement = joint.compute_rotation_to_direction(normal, self.source_direction)
            else:
                movement = joint.compute_rotation_to_point(target, normal, self.source_direction)
            self.object_movements_map[obj] = movement

    def make_movements(self):
        for obj in self.object_movements_map:
            movement = self.object_movements_map[obj]
            obj.Placement = movement.multiply(obj.Placement)
            for element, el_obj in self.scene.element_object_dict.items():
                if obj == el_obj:
                    element.Placement = movement.multiply(element.Placement)
        self.scene.recompute_boundbox()

    def undo_movements(self):
        for obj in self.object_movements_map:
            movement = self.object_movements_map[obj]
            movement = movement.inverse()
            obj.Placement = movement.multiply(obj.Placement)
            for element, el_obj in self.scene.element_object_dict.items():
                if obj == el_obj:
                    element.Placement = movement.multiply(element.Placement)
        self.scene.recompute_boundbox()
