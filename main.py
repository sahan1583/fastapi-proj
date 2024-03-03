from pydantic import BaseModel
from typing import Optional
from pymongo import MongoClient
from models import Asset, PerformanceMetrics
from fastapi import FastAPI, HTTPException, status, Depends, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from dotenv import load_dotenv
import os
from stats import SummaryStatistics
load_dotenv()


app = FastAPI()

client = MongoClient(os.getenv("MONGODB_URI"))
database = client[os.getenv("DATABASE")]
assetCollection = database["asset"]
pmCollection = database["performanceMetrics"]


SECRET_KEY = "83daa0256a2289b0fb23693bf1f6034d44396675749244721a2b20e896e11662"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

db = {
    "tim": {
        "username": "tim",
        "full_name": "Tim Ruscica",
        "email": "tim@gmail.com",
        "hashed_password": "$2b$12$HxWHkvMuL7WrZad6lcCfluNFj1/Zp63lvP5aUrKlSTYtoFzPXHOtu",
        "disabled": False
    }
}


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str or None = None


class User(BaseModel):
    username: str
    email: str or None = None
    full_name: str or None = None
    disabled: bool or None = None


class UserInDB(User):
    hashed_password: str


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

app = FastAPI()


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def get_user(db, username: str):
    if username in db:
        user_data = db[username]
        return UserInDB(**user_data)


def authenticate_user(db, username: str, password: str):
    user = get_user(db, username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False

    return user


def create_access_token(data: dict, expires_delta: timedelta or None = None):  # type: ignore
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credential_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                         detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credential_exception

        token_data = TokenData(username=username)
    except JWTError:
        raise credential_exception

    user = get_user(db, username=token_data.username)
    if user is None:
        raise credential_exception

    return user


async def get_current_active_user(current_user: UserInDB = Depends(get_current_user)):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")

    return current_user


@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/create_asset/")
async def create_asset(asset: Asset, current_user: str = Depends(get_current_user)):

    if assetCollection.find_one({"AssetID": asset.AssetID}):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Asset with ID:{asset.AssetID} already exists")
    if len(asset.dict(exclude_none=True)) != 7:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Insufficient number of fields")
    result = assetCollection.insert_one(asset.dict())
    return {"message": f"Asset with id:{asset.AssetID} created successfully"}


@app.get("/read_asset/{asset_id}")
async def read_asset(asset_id: int, current_user: str = Depends(get_current_user)):
    asset = assetCollection.find_one({"AssetID": asset_id})
    asset.pop("_id")
    return asset


@app.put("/update_asset/")
async def update_asset(asset: Asset, current_user: str = Depends(get_current_user)):
    result = assetCollection.update_one({"AssetID": asset.AssetID}, {
                                        "$set": asset.dict(exclude_defaults=True)})
    # print(result)
    return f"successfully updated the asset with id:{asset.AssetID}"


@app.delete("/delete_asset/{asset_id}")
async def delete_asset(asset_id: int, current_user: str = Depends(get_current_user)):
    result = assetCollection.delete_one({"AssetID": asset_id})
    # print(result)
    return f"successfully deleted the asset with id:{asset_id}"


@app.post("/create_pm/")
async def create_pm(pm: PerformanceMetrics, current_user: str = Depends(get_current_user)):
    if pmCollection.find_one({"AssetID": pm.AssetID}):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"performance metric for Asset with ID:{pm.AssetID} already exists")
    if len(pm.dict()) != 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Insufficient number of fields")

    result = pmCollection.insert_one(pm.dict())
    return {"message": f"pmetric for assetid:{pm.AssetID} created successfully"}


@app.get("/read_pm/{asset_id}")
async def read_pm(asset_id: int, current_user: str = Depends(get_current_user)):
    pm = pmCollection.find_one({"AssetID": asset_id})
    pm.pop("_id")
    return pm


@app.put("/update_pm/")
async def update_pm(pm: PerformanceMetrics, current_user: str = Depends(get_current_user)):
    result = pmCollection.update_one({"AssetID": pm.AssetID}, {
                                     "$set": pm.dict(exclude_defaults=True)})
    # print(result)
    return f"successfully update the asset with id:{pm.AssetID}"


@app.delete("/delete_pm/{asset_id}")
async def delete_pm(asset_id: int, current_user: str = Depends(get_current_user)):
    result = pmCollection.delete_one({"AssetID": asset_id})
    # print(result)
    return f"successfully deleted the asset with id:{asset_id}"


@app.get("/stats/")
async def stats(current_user: str = Depends(get_current_user)):
    records = pmCollection.find()
    records = [record for record in records]
    # print(records)
    return SummaryStatistics(records)
