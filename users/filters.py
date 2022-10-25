from django_filters import rest_framework as filters

from users.models import CustomUser


class UserFilter(filters.FilterSet):
    """
    Filter for Users

    ?about_me__contains=clown - equal to .filter(about_me__contains='clown')
    ?key_skills__contains=clown - equal to .filter(key_skills__contains='clown')
    ?useful_to_project__contains=clown - equal to .filter(useful_to_project__contains='clown')

    ?first_name=clown - equal to .filter(first_name='clown')
    ?last_name=clown - equal to .filter(last_name='clown')
    ?patronymic=clown - equal to .filter(patronymic='clown')
    ?speciality=clown - equal to .filter(speciality='clown')
    ?city=clown - equal to .filter(city='clown')
    ?region=clown - equal to .filter(region='clown')
    ?organization=clown - equal to .filter(organization='clown')
    """

    about_me__contains = filters.Filter(field_name='about_me', lookup_expr='contains')
    key_skills__contains = filters.Filter(field_name='key_skills', lookup_expr='contains')
    useful_to_project__contains = filters.Filter(field_name='useful_to_project', lookup_expr='contains')

    class Meta:
        model = CustomUser
        fields = (
            'first_name', 'last_name', 'patronymic', 'speciality', 'city', 'region', 'organization'
        )
