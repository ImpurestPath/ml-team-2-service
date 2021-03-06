from typing import List

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db.utils import OperationalError, ProgrammingError
from .models import Wine, User, Review
from .serializers import (
    WineSerializer,
    UserSerializer,
    ReviewSerializer,
    ReviewModelSerializer,
)
from tqdm import tqdm
import pandas as pd
import numpy as np
from .recommendation_model import model


def build_adjacency_matrix() -> pd.DataFrame:
    print("Start building adjacency matrix")
    users = User.objects.all()
    wines = Wine.objects.order_by("pk").all()
    wine_pk_wine_id = dict(zip([wine.pk for wine in wines], range(len(wines))))
    adjacency_matrix = []
    for user in tqdm(users):
        user_reviews = Review.objects.filter(user_id=user.pk)
        result = [int(user.pk)] + [None] * len(wines)
        for review in user_reviews:
            result[wine_pk_wine_id[review.wine.pk] + 1] = (
                review.rating / review.variants
            )

        adjacency_matrix.append(result)
    adjacency_matrix = pd.DataFrame(
        adjacency_matrix, columns=["user_id", *[wine.pk for wine in wines]]
    )
    print("Finish building adjacency matrix")

    return adjacency_matrix


def most_popular_wines(adjacency_matrix: pd.DataFrame) -> List[int]:
    most_popular = np.argsort(adjacency_matrix.sum(axis=0))
    most_popular_index = adjacency_matrix.index[most_popular][::-1]
    return most_popular_index


try:
    adjacency_matrix = build_adjacency_matrix()
    most_popular_index = most_popular_wines(adjacency_matrix)
except OperationalError:
    pass
except ProgrammingError:
    pass


@api_view(["GET", "POST"])
def user_list(request):
    """
    Получить всех пользователей или добавить нового
    """
    if request.method == "GET":
        user = User.objects.all()
        serializer = UserSerializer(user, many=True)
        return Response(serializer.data)
    elif request.method == "POST":
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            global adjacency_matrix
            adjacency_matrix.loc[len(adjacency_matrix)] = [
                int(serializer.data["id"])
            ] + [None] * (adjacency_matrix.shape[1] - 1)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# TODO: добавить матчинг по названиям
@api_view(["GET", "POST"])
def wine_list(request):
    """
    Получить все вина или добавить новое
    """
    if request.method == "GET":
        wine = Wine.objects.all()
        serializer = WineSerializer(wine, many=True)
        return Response(serializer.data)
    elif request.method == "POST":
        serializer = WineSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            global adjacency_matrix
            adjacency_matrix[serializer.data["id"]] = [None] * adjacency_matrix.shape[0]
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
def review_list(request):
    """
    Добавить или изменить оценку пользователя по конкретному вину
    """
    serializer = ReviewSerializer(data=request.data)
    if serializer.is_valid():
        try:
            wine = Wine.objects.get(internal_id__exact=serializer.data["wine"])
            user = User.objects.get(internal_id__exact=serializer.data["user"])
        except Wine.DoesNotExist:
            return Response(
                f"Wine with id {serializer.data['wine']} does not exist",
                status.HTTP_400_BAD_REQUEST,
            )
        except User.DoesNotExist:
            return Response(
                f"User with id {serializer.data['user']} does not exist",
                status.HTTP_400_BAD_REQUEST,
            )
        try:
            review = Review.objects.get(wine=wine, user=user)
        except Review.DoesNotExist:
            review = Review()
        serializer = ReviewModelSerializer(
            review,
            data={
                "rating": request.data["rating"],
                "variants": request.data["variants"],
                "wine": wine.pk,
                "user": user.pk,
            },
        )
        if serializer.is_valid():
            serializer.save()
            global adjacency_matrix, most_popular_index
            index = adjacency_matrix[adjacency_matrix["user_id"] == user.pk].index[0]
            adjacency_matrix.loc[index, wine.pk] = float(
                request.data["rating"]
            ) / float(request.data["variants"])
            most_popular_index = most_popular_wines(adjacency_matrix)
            return Response({"result": "ok"}, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
def get_recommendations(request, user_id):
    """
    Получить рекомендацию по конкретному пользователю
    """
    global adjacency_matrix
    # TODO: получать по внешнему user_id внутренний user_id
    wines_id = model(adjacency_matrix, most_popular_index, user_id)
    offset = int(request.query_params.get("offset", 0))
    amount = int(request.query_params.get("amount", 20))
    print(offset, amount)
    return Response({"wine_id": wines_id[offset:amount]}, status=status.HTTP_200_OK)


@api_view(["GET"])
def print_matrix(request):
    global adjacency_matrix
    print(adjacency_matrix)
    return Response({}, status.HTTP_200_OK)
