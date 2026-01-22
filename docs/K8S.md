### Update Your Token

Link: [https://k8s.slac.stanford.edu/lcls-dataminer](https://k8s.slac.stanford.edu/lcls-dataminer)

### Configure kubectl and Get API Key

```bash
# Switch to the lcls-dataminer cluster
kubectl config use-context lcls-dataminer

# Set default namespace to tiled-dev
kubectl config set-context --current --namespace=tiled-dev

# Retrieve the Tiled API key secret
kubectl get secret tiled-api-key-6hhc25f4mk -o yaml

# Decode the base64 secret
echo "XXXXX" | base64 -d
```
